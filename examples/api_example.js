/**
 * SeedVR2 API 调用示例（Node.js）
 *
 * 本脚本演示如何通过 Node.js fetch API 调用 SeedVR2 的 REST API，
 * 涵盖以下场景：
 * 1. 单文件上传修复
 * 2. 批量文件夹修复
 * 3. SSE 实时进度监听
 * 4. 历史记录查询
 * 5. 结果文件下载
 * 6. 系统健康检查与 GPU 信息查询
 * 7. 模型加载/状态查询
 *
 * 使用前请确保：
 * 1. SeedVR2 服务已启动（默认 http://127.0.0.1:7870）
 * 2. 模型已加载（可通过 /api/system/model/load 加载）
 * 3. Node.js 18+（内置 fetch 和 FormData）
 *
 * Usage:
 *   node api_example.js [--base-url http://127.0.0.1:7870]
 */

const { readFileSync, createWriteStream, existsSync, mkdirSync } = require('fs');
const { join, dirname, basename } = require('path');

// 解析命令行参数
const args = process.argv.slice(2);
let BASE_URL = 'http://127.0.0.1:7870';
for (let i = 0; i < args.length; i++) {
    if (args[i] === '--base-url' && args[i + 1]) {
        BASE_URL = args[i + 1];
        i++;
    }
}

/**
 * 健康检查
 * GET /api/system/ping — 轻量级存活探针
 * GET /api/system/health — 详细系统健康检查
 */
async function checkHealth() {
    console.log('\n=== 1. 健康检查 ===');

    // 轻量探针
    const pingResp = await fetch(`${BASE_URL}/api/system/ping`);
    const ping = await pingResp.json();
    console.log(`  Ping: status=${ping.status}, version=${ping.version}, gpu=${ping.gpu_available}`);

    // 详细健康检查
    const healthResp = await fetch(`${BASE_URL}/api/system/health`);
    const health = await healthResp.json();
    console.log(`  Status: ${health.status}`);
    console.log(`  Uptime: ${health.uptime_seconds?.toFixed(1)}s`);
    const sys = health.system || {};
    console.log(`  Platform: ${sys.platform || 'unknown'}`);
    console.log(`  Python: ${sys.python_version || 'unknown'}`);
    console.log(`  CPU cores: ${sys.cpu_count || 0}`);
    console.log(`  Memory: ${sys.memory_available_gb?.toFixed(1) || 0} / ${sys.memory_total_gb?.toFixed(1) || 0} GB`);
    const gpu = health.gpu || {};
    console.log(`  GPU: ${gpu.device_name || 'N/A'} (available=${gpu.is_gpu_available})`);

    return health;
}

/**
 * 获取 GPU 详细信息
 * GET /api/system/gpu — GPU 硬件信息
 * GET /api/system/gpu/vram-estimate — VRAM 需求估算
 * GET /api/system/gpu/recommend-params — 推荐参数
 */
async function getGpuInfo() {
    console.log('\n=== 2. GPU 信息 ===');

    const resp = await fetch(`${BASE_URL}/api/system/gpu`);
    const gpu = await resp.json();
    console.log(`  Device: ${gpu.device_name || 'N/A'}`);
    console.log(`  VRAM: ${gpu.vram_available_mb || 0} / ${gpu.vram_total_mb || 0} MB`);
    console.log(`  Utilization: ${gpu.utilization_pct || 0}%`);
    console.log(`  CUDA: ${gpu.cuda_version || 'N/A'}`);

    // VRAM 估算
    console.log('\n  --- VRAM 估算 ---');
    const estParams = new URLSearchParams({
        model_name: '3b', precision: 'fp16',
        width: '1920', height: '1080', num_frames: '1'
    });
    const estResp = await fetch(`${BASE_URL}/api/system/gpu/vram-estimate?${estParams}`);
    const est = await estResp.json();
    if (est.success) {
        const d = est.data;
        console.log(`  Model: ${d.model_name} (${d.precision})`);
        console.log(`  Input: ${d.input_width}x${d.input_height}, ${d.num_frames} frames`);
        console.log(`  Estimated VRAM: ${d.estimated_vram_gb.toFixed(2)} GB`);
    }

    // 参数推荐
    console.log('\n  --- 参数推荐 ---');
    const recParams = new URLSearchParams({
        model_name: '3b',
        width: '1920', height: '1080', num_frames: '1'
    });
    const recResp = await fetch(`${BASE_URL}/api/system/gpu/recommend-params?${recParams}`);
    const rec = await recResp.json();
    if (rec.success) {
        const r = rec.data;
        console.log(`  Recommended precision: ${r.precision}`);
        console.log(`  BlockSwap: ${r.enable_blockswap} (blocks=${r.blocks_to_swap})`);
        console.log(`  Risk: ${r.risk}`);
    }

    return gpu;
}

/**
 * 加载模型到 GPU
 * POST /api/system/model/load — 加载模型
 * GET /api/system/model/status — 查询模型状态
 */
async function loadModel(size = '3b', precision = 'fp16') {
    console.log(`\n=== 3. 加载模型 (${size}/${precision}) ===`);

    // 先检查当前状态
    const statusResp = await fetch(`${BASE_URL}/api/system/model/status`);
    const status = await statusResp.json();
    if (status.loaded) {
        console.log(`  模型已加载: ${status.model_size || 'unknown'}`);
        return status;
    }

    // 加载模型
    const resp = await fetch(`${BASE_URL}/api/system/model/load`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ size, precision }),
    });
    if (resp.ok) {
        const result = await resp.json();
        console.log(`  加载成功: ${JSON.stringify(result)}`);
        return result;
    } else {
        const text = await resp.text();
        console.log(`  加载失败: ${resp.status} - ${text}`);
        return {};
    }
}

/**
 * 上传单文件并创建修复任务
 * POST /api/restore/ — 上传文件创建修复任务
 *
 * @param {string} filePath - 本地文件路径
 * @returns {Promise<string|null>} - 任务 ID
 */
async function uploadAndRestore(filePath) {
    console.log(`\n=== 4. 单文件修复: ${filePath} ===`);

    if (!existsSync(filePath)) {
        console.log(`  文件不存在: ${filePath}`);
        return null;
    }

    const fileBuffer = readFileSync(filePath);
    const fileName = basename(filePath);
    const formData = new FormData();
    formData.append('file', new Blob([fileBuffer]), fileName);
    formData.append('task_type', 'auto');
    formData.append('dit_model', '3b_fp16');
    formData.append('seed', '42');
    formData.append('resolution', '2048');

    const resp = await fetch(`${BASE_URL}/api/restore/`, {
        method: 'POST',
        body: formData,
    });

    if (resp.ok) {
        const result = await resp.json();
        if (result.success) {
            const task = result.data;
            console.log(`  任务已创建:`);
            console.log(`    Task ID: ${task.task_id}`);
            console.log(`    Record ID: ${task.record_id}`);
            console.log(`    Type: ${task.task_type}`);
            console.log(`    Status: ${task.status}`);
            return task.task_id;
        } else {
            console.log(`  创建失败: ${result.error}`);
            return null;
        }
    } else {
        const text = await resp.text();
        console.log(`  请求失败: ${resp.status} - ${text}`);
        return null;
    }
}

/**
 * 批量修复文件夹中的媒体文件
 * POST /api/restore/batch — 创建批量修复任务
 *
 * @param {string} folderPath - 服务器上的文件夹路径
 * @returns {Promise<string|null>} - 批量任务 ID
 */
async function batchRestore(folderPath) {
    console.log(`\n=== 5. 批量修复: ${folderPath} ===`);

    const formData = new FormData();
    formData.append('folder_path', folderPath);
    formData.append('task_type', 'auto');
    formData.append('dit_model', '3b_fp16');
    formData.append('seed', '42');

    const resp = await fetch(`${BASE_URL}/api/restore/batch`, {
        method: 'POST',
        body: formData,
    });

    if (resp.ok) {
        const result = await resp.json();
        if (result.success) {
            const batch = result.data;
            console.log(`  批量任务已创建:`);
            console.log(`    Batch ID: ${batch.batch_id}`);
            console.log(`    Total files: ${batch.total}`);
            console.log(`    Media type: ${batch.media_type}`);
            return batch.batch_id;
        } else {
            console.log(`  创建失败: ${result.error}`);
            return null;
        }
    } else {
        const text = await resp.text();
        console.log(`  请求失败: ${resp.status} - ${text}`);
        return null;
    }
}

/**
 * 通过 SSE 监听任务实时进度
 * GET /api/restore/{taskId}/progress — SSE 实时进度推送
 *
 * 使用 Node.js 的 HTTP 模块处理 SSE 流。
 *
 * @param {string} taskId - 任务 ID
 * @param {number} timeout - 最大监听时间（毫秒）
 */
async function listenSseProgress(taskId, timeout = 300000) {
    console.log(`\n=== 6. SSE 进度监听 (task=${taskId}) ===`);

    return new Promise((resolve) => {
        const url = new URL(`${BASE_URL}/api/restore/${taskId}/progress`);
        const http = require(url.protocol === 'https:' ? 'https' : 'http');

        const req = http.get(url, (res) => {
            let buffer = '';
            const timer = setTimeout(() => {
                console.log('  超时，停止监听');
                req.destroy();
                resolve();
            }, timeout);

            res.on('data', (chunk) => {
                buffer += chunk.toString();
                const lines = buffer.split('\n');
                buffer = lines.pop(); // 保留最后未完整的行

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6);
                        try {
                            const data = JSON.parse(dataStr);
                            const status = data.status || 'unknown';
                            const progress = data.progress || 0;
                            const currentFrame = data.current_frame || 0;
                            const totalFrames = data.total_frames || 0;
                            const message = data.message || '';

                            if (totalFrames > 0) {
                                console.log(`  [${status}] ${progress.toFixed(1)}% (frame ${currentFrame}/${totalFrames}) ${message}`);
                            } else {
                                console.log(`  [${status}] ${progress.toFixed(1)}% ${message}`);
                            }

                            // 终态处理
                            if (['completed', 'failed', 'cancelled', 'timeout'].includes(status)) {
                                console.log(`  任务结束: ${status}`);
                                clearTimeout(timer);
                                req.destroy();
                                resolve();
                            }
                        } catch (e) {
                            // 忽略 JSON 解析错误
                        }
                    }
                }
            });

            res.on('end', () => {
                clearTimeout(timer);
                resolve();
            });

            res.on('error', (e) => {
                console.log(`  SSE 监听异常: ${e.message}`);
                clearTimeout(timer);
                resolve();
            });
        });

        req.on('error', (e) => {
            console.log(`  连接失败: ${e.message}`);
            resolve();
        });
    });
}

/**
 * 获取任务结果信息
 * GET /api/restore/{taskId}/result
 */
async function getTaskResult(taskId) {
    console.log(`\n=== 7. 获取结果 (task=${taskId}) ===`);

    const resp = await fetch(`${BASE_URL}/api/restore/${taskId}/result`);
    if (resp.ok) {
        const result = await resp.json();
        if (result.success) {
            const data = result.data;
            console.log(`  Status: ${data.status}`);
            if (data.output_path) console.log(`  Output: ${data.output_path}`);
            if (data.file_size) console.log(`  Size: ${data.file_size} bytes`);
            if (data.error) console.log(`  Error: ${data.error}`);
            return data;
        }
    } else {
        console.log(`  请求失败: ${resp.status}`);
    }
    return null;
}

/**
 * 下载修复结果文件
 * GET /api/restore/{taskId}/download
 */
async function downloadResult(taskId, outputDir = 'downloads') {
    console.log(`\n=== 8. 下载结果 (task=${taskId}) ===`);

    if (!existsSync(outputDir)) {
        mkdirSync(outputDir, { recursive: true });
    }

    const resp = await fetch(`${BASE_URL}/api/restore/${taskId}/download`);

    if (resp.ok) {
        // 从 Content-Disposition 获取文件名
        const contentDisp = resp.headers.get('content-disposition') || '';
        let filename = taskId;
        const match = contentDisp.match(/filename="?([^";\n]+)"?/);
        if (match) {
            filename = match[1];
        }

        // 如果没有扩展名，根据 Content-Type 推断
        if (!filename.includes('.')) {
            const contentType = resp.headers.get('content-type') || '';
            const extMap = { 'image/png': '.png', 'image/jpeg': '.jpg', 'video/mp4': '.mp4' };
            filename += extMap[contentType] || '.bin';
        }

        const outputPath = join(outputDir, filename);
        const buffer = Buffer.from(await resp.arrayBuffer());
        const { writeFileSync, statSync } = require('fs');
        writeFileSync(outputPath, buffer);
        console.log(`  已下载: ${outputPath} (${statSync(outputPath).size} bytes)`);
    } else {
        const text = await resp.text();
        console.log(`  下载失败: ${resp.status} - ${text}`);
    }
}

/**
 * 查询历史记录
 * GET /api/system/history — 获取历史记录列表
 * GET /api/system/history/statistics — 获取统计数据
 */
async function queryHistory(page = 1, pageSize = 10) {
    console.log('\n=== 9. 历史记录查询 ===');

    // 统计数据
    const statsResp = await fetch(`${BASE_URL}/api/system/history/statistics`);
    const stats = await statsResp.json();
    console.log(`  统计: ${JSON.stringify(stats)}`);

    // 历史记录列表
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    const resp = await fetch(`${BASE_URL}/api/system/history?${params}`);
    const history = await resp.json();
    const records = history.records || [];
    console.log(`  总记录: ${history.total || 0}, 第 ${page} 页, 每页 ${pageSize} 条`);
    for (const record of records.slice(0, 5)) {
        const inputFile = (record.input_file || 'N/A').substring(0, 50);
        console.log(`    [${record.id}] ${record.task_type} | ${record.status} | ${inputFile}`);
    }
}

/**
 * 主函数 — 演示完整的 API 调用流程
 */
async function main() {
    console.log(`SeedVR2 API 示例 — 服务地址: ${BASE_URL}`);

    try {
        // 1. 健康检查
        await checkHealth();

        // 2. GPU 信息
        await getGpuInfo();

        // 3. 加载模型
        await loadModel('3b', 'fp16');

        // 4. 单文件修复（如果有测试文件）
        const testImage = join(__dirname, 'sample.jpg');
        if (existsSync(testImage)) {
            const taskId = await uploadAndRestore(testImage);
            if (taskId) {
                // 6. SSE 进度监听
                await listenSseProgress(taskId, 300000);
                // 7. 获取结果
                await getTaskResult(taskId);
                // 8. 下载结果
                await downloadResult(taskId);
            }
        } else {
            console.log(`\n  (跳过单文件修复：未找到测试文件 ${testImage})`);
            console.log('  请放置一张图片到 examples/sample.jpg 以测试完整流程');
        }

        // 5. 批量修复示例（注释掉，需要真实文件夹路径）
        // await batchRestore('/path/to/your/image/folder');

        // 9. 历史记录查询
        await queryHistory();

        console.log('\n=== 示例完成 ===');
    } catch (error) {
        console.error(`\n错误: ${error.message}`);
        if (error.cause) {
            console.error(`  原因: ${error.cause.message || error.cause}`);
        }
        console.error('  请确认 SeedVR2 服务已启动并监听在', BASE_URL);
    }
}

main();
