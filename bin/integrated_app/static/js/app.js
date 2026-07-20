/**
 * SeedVR2 工具箱 - 前端交互脚本
 * 包含：API 封装、文件上传、SSE 进度、对比滑块、Toast 通知、侧边栏状态等
 */

const SeedVR2 = (() => {
    'use strict';

    // ===== 客户端 i18n =====
    const _translations = {
        zh: {
            'error.400': '请求参数有误',
            'error.401': '请先登录',
            'error.403': '没有权限执行此操作',
            'error.404': '请求的资源不存在',
            'error.408': '请求超时，请重试',
            'error.409': '操作冲突，请刷新后重试',
            'error.422': '提交的数据格式有误',
            'error.429': '操作过于频繁，请稍后再试',
            'error.500': '服务器内部错误，请稍后重试',
            'error.502': '服务暂时不可用',
            'error.503': '服务维护中，请稍后重试',
            'error.504': '请求超时，请重试',
            'error.default': '请求失败',
            'error.request_failed': '请求失败',
            'error.send_failed': '发送请求失败',
            'error.network_error': '网络错误',
            'dir.empty': '空目录',
            'dir.enter_path': '请输入路径',
            'dir.opened': '已在文件管理器中打开',
            'dir.open_failed': '打开失败',
            'dir.loading': '加载中...',
            'dir.error': '加载失败',
            'time.day': '天',
            'time.hour': '时',
            'time.minute': '分',
            'time.second': '秒',
            'task.canceled': '任务已取消',
            'task.cancel_failed': '取消失败',
            'history.delete_confirm_title': '删除记录',
            'history.delete_confirm_msg': '确定要删除此记录吗？',
            'history.record_deleted': '记录已删除',
            'history.delete_failed': '删除失败',
            'locale.switched': '语言已切换',
            'locale.switch_failed': '语言切换失败',
        },
        en: {
            'error.400': 'Invalid request parameters',
            'error.401': 'Please log in first',
            'error.403': 'Permission denied',
            'error.404': 'Resource not found',
            'error.408': 'Request timeout, please retry',
            'error.409': 'Conflict, please refresh and retry',
            'error.422': 'Invalid data format',
            'error.429': 'Too many requests, please try later',
            'error.500': 'Internal server error, please try later',
            'error.502': 'Service temporarily unavailable',
            'error.503': 'Service under maintenance',
            'error.504': 'Request timeout, please retry',
            'error.default': 'Request failed',
            'error.request_failed': 'Request failed',
            'error.send_failed': 'Send request failed',
            'error.network_error': 'Network error',
            'dir.empty': 'Empty directory',
            'dir.enter_path': 'Please enter a path',
            'dir.opened': 'Opened in file explorer',
            'dir.open_failed': 'Failed to open',
            'dir.loading': 'Loading...',
            'dir.error': 'Error loading directory',
            'time.day': 'd',
            'time.hour': 'h',
            'time.minute': 'm',
            'time.second': 's',
            'task.canceled': 'Task canceled',
            'task.cancel_failed': 'Cancel failed',
            'history.delete_confirm_title': 'Delete Record',
            'history.delete_confirm_msg': 'Are you sure you want to delete this record?',
            'history.record_deleted': 'Record deleted',
            'history.delete_failed': 'Delete failed',
            'locale.switched': 'Language switched',
            'locale.switch_failed': 'Language switch failed',
        }
    };

    // Simple i18n lookup - falls back to Chinese if translation not found
    function t(key) {
        const locale = window.__LOCALE__ || 'zh';
        const dict = _translations[locale] || _translations.zh;
        return dict[key] || _translations.zh[key] || key;
    }

    // ===== API 封装 =====
    function httpStatusText(status) {
        return t(`error.${status}`) || `${t('error.default')} (${status})`;
    }

    function parseApiError(response, data) {
        if (data?.error?.message) return data.error.message;
        if (data?.detail) return typeof data.detail === 'string' ? data.detail : httpStatusText(response.status);
        return httpStatusText(response.status);
    }

    // ===== CSRF Token Helper =====
    function getCsrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
        return match ? decodeURIComponent(match[1]) : null;
    }

    function csrfHeaders() {
        const token = getCsrfToken();
        return token ? { 'X-CSRF-Token': token } : {};
    }

    const api = {
        async get(url) {
            const response = await fetch(url);
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(parseApiError(response, data));
            }
            return response.json();
        },

        async post(url, data) {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...csrfHeaders() },
                body: JSON.stringify(data),
            });
            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(parseApiError(response, errData));
            }
            return response.json();
        },

        async delete(url) {
            const response = await fetch(url, {
                method: 'DELETE',
                headers: csrfHeaders(),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(parseApiError(response, data));
            }
            return response.json();
        },

        async uploadRestore(formData) {
            const token = getCsrfToken();
            const headers = token ? { 'X-CSRF-Token': token } : {};
            const response = await fetch('/api/restore', {
                method: 'POST',
                headers,
                body: formData,
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(parseApiError(response, data));
            }
            return response.json();
        },

        async submitWithLoading(btn, promise, options = {}) {
            if (!btn || !(btn instanceof Element)) return promise;
            const originalHtml = btn.innerHTML;
            const spinner = options.loadingHtml || '<span class="sv-spinner sv-spinner-sm"></span>';
            const loadingText = options.loadingText || '';
            btn.disabled = true;
            btn.innerHTML = spinner + (loadingText ? ' ' + loadingText : '');
            try {
                return await promise;
            } finally {
                btn.disabled = false;
                if (options.restoreHtml !== false) {
                    btn.innerHTML = originalHtml;
                }
            }
        },
    };

    // ===== Toast 通知 =====
    const MAX_TOASTS = 3;

    function toast(message, type = 'info', duration = 4000) {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        // 限制最大数量
        while (container.children.length >= MAX_TOASTS) {
            const oldest = container.firstElementChild;
            oldest.classList.add('toast-out');
            setTimeout(() => oldest.remove(), 300);
        }

        const iconMap = {
            success: 'bi-check-circle-fill',
            error: 'bi-exclamation-circle-fill',
            warning: 'bi-exclamation-triangle-fill',
            info: 'bi-info-circle-fill',
        };

        const el = document.createElement('div');
        el.className = `sv-toast toast-${type}`;

        const iconEl = document.createElement('i');
        iconEl.className = `bi ${iconMap[type] || iconMap.info}`;

        const msgSpan = document.createElement('span');
        msgSpan.style.flex = '1';
        msgSpan.textContent = message;

        const closeBtn = document.createElement('button');
        closeBtn.className = 'sv-toast-close';
        const i18n = window.__I18N__ || {};
        closeBtn.setAttribute('aria-label', i18n['common.close'] || 'Close');
        closeBtn.addEventListener('click', () => {
            el.classList.add('toast-out');
            setTimeout(() => el.remove(), 300);
        });

        const closeIcon = document.createElement('i');
        closeIcon.className = 'bi bi-x';
        closeBtn.appendChild(closeIcon);

        el.appendChild(iconEl);
        el.appendChild(msgSpan);
        el.appendChild(closeBtn);

        container.appendChild(el);

        setTimeout(() => {
            el.classList.add('toast-out');
            setTimeout(() => el.remove(), 300);
        }, duration);
    }

    // ===== 确认模态框 =====
    function confirm(title, message, onConfirm) {
        const modal = document.getElementById('confirmModal');
        const titleEl = document.getElementById('confirmTitle');
        const msgEl = document.getElementById('confirmMessage');
        const actionBtn = document.getElementById('confirmAction');

        if (!modal || !titleEl || !msgEl || !actionBtn) return;

        titleEl.textContent = title;
        msgEl.textContent = message;

        // 终止之前的事件监听
        if (modal._confirmAbortController) {
            modal._confirmAbortController.abort();
        }
        const controller = new AbortController();
        modal._confirmAbortController = controller;

        actionBtn.addEventListener('click', () => {
            closeModal('confirmModal');
            if (typeof onConfirm === 'function') onConfirm();
        }, { signal: controller.signal });

        modal.classList.add('show');
    }

    function trapFocus(modalEl) {
        const focusable = modalEl.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        first.focus();

        function handleTab(e) {
            if (e.key !== 'Tab') return;
            if (e.shiftKey) {
                if (document.activeElement === first) {
                    e.preventDefault();
                    last.focus();
                }
            } else {
                if (document.activeElement === last) {
                    e.preventDefault();
                    first.focus();
                }
            }
        }

        modalEl.addEventListener('keydown', handleTab);
        modalEl._focusTrapHandler = handleTab;
        modalEl._firstFocusable = first;
    }

    function releaseFocus(modalEl) {
        if (modalEl._focusTrapHandler) {
            modalEl.removeEventListener('keydown', modalEl._focusTrapHandler);
            delete modalEl._focusTrapHandler;
        }
    }

    function openModal(id) {
        const modal = document.getElementById(id);
        if (modal) {
            modal._previousFocus = document.activeElement;
            modal.classList.add('show');
            trapFocus(modal);
        }
    }

    function closeModal(id) {
        const modal = document.getElementById(id);
        if (modal) {
            releaseFocus(modal);
            modal.classList.add('hiding');
            modal.classList.remove('show');
            setTimeout(() => {
                modal.classList.remove('hiding');
            }, 250);
            if (modal._previousFocus) {
                modal._previousFocus.focus();
                modal._previousFocus = null;
            }
        }
    }

    // ===== 文件上传区域 =====
    function setupUploadZone(zone, fileInput, callbacks = {}) {
        if (!zone || !fileInput) return;

        // 点击上传
        zone.addEventListener('click', (e) => {
            if (e.target !== fileInput) {
                fileInput.click();
            }
        });

        // 文件选择
        fileInput.addEventListener('change', () => {
            if (fileInput.files && fileInput.files[0]) {
                zone.classList.add('has-file');
                if (callbacks.onFileSelected) callbacks.onFileSelected(fileInput.files[0]);
            } else {
                zone.classList.remove('has-file');
                if (callbacks.onFileCleared) callbacks.onFileCleared();
            }
        });

        // 拖拽事件
        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.add('drag-over');
        });

        zone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.remove('drag-over');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.remove('drag-over');

            const files = e.dataTransfer.files;
            if (files && files[0]) {
                // 使用 DataTransfer 设置文件
                const dt = new DataTransfer();
                dt.items.add(files[0]);
                fileInput.files = dt.files;

                zone.classList.add('has-file');
                if (callbacks.onFileSelected) callbacks.onFileSelected(files[0]);
            }
        });
    }

    // ===== 全局 SSE 连接 =====
    let globalEventSource = null;

    function initGlobalSSE() {
        if (globalEventSource) {
            globalEventSource.close();
            globalEventSource = null;
        }

        globalEventSource = new EventSource('/api/sse/events');
        window.__sseConnection = globalEventSource;

        globalEventSource.addEventListener('heartbeat', (event) => {
            try {
                const data = JSON.parse(event.data);
                console.log('SSE heartbeat:', data);
            } catch (err) {
                console.error('SSE heartbeat parse error:', err);
            }
        });

        globalEventSource.addEventListener('progress', (event) => {
            try {
                const data = JSON.parse(event.data);
                console.log('SSE progress:', data);
            } catch (err) {
                console.error('SSE progress parse error:', err);
            }
        });

        globalEventSource.addEventListener('model_status', (event) => {
            try {
                const data = JSON.parse(event.data);
                console.log('SSE model_status:', data);
            } catch (err) {
                console.error('SSE model_status parse error:', err);
            }
        });

        globalEventSource.onerror = () => {
            console.warn('SSE connection error, will retry automatically');
        };

        window.addEventListener('beforeunload', () => {
            if (globalEventSource) {
                globalEventSource.close();
                globalEventSource = null;
                window.__sseConnection = null;
            }
        });
    }

    // ===== SSE 统一修复进度 =====
    let currentRestoreEventSource = null;

    function startRestoreProgressSSE(taskId, taskType) {
        // 关闭之前的连接
        if (currentRestoreEventSource) {
            currentRestoreEventSource.close();
            currentRestoreEventSource = null;
        }

        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');
        const progressPct = document.getElementById('progressPct');
        const progressFrames = document.getElementById('progressFrames');
        const progressEta = document.getElementById('progressEta');
        const taskStatus = document.getElementById('taskStatus');

        const es = new EventSource(`/api/restore/${taskId}/progress`);
        currentRestoreEventSource = es;

        let startTime = Date.now();
        const _I = window.__I18N__ || {};
        const typeLabel = taskType === 'video' ? (_I['history.video'] || t('history.video')) : (_I['history.image'] || t('history.image'));

        es.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // 更新进度条
                if (progressBar) {
                    progressBar.style.width = `${data.progress}%`;
                    progressBar.setAttribute('aria-valuenow', Math.round(data.progress));
                    if (data.progress >= 100) {
                        progressBar.classList.remove('animated');
                        progressBar.classList.add('bg-success');
                    }
                }

                // 更新文本
                if (progressPct) progressPct.textContent = `${data.progress}%`;
                if (progressFrames) {
                    if (taskType === 'video') {
                        progressFrames.textContent = ` ${I['video.batch_current_processing']?.replace('{current}', data.current_frame).replace('{total}', data.total_frames) || `${data.current_frame} / ${data.total_frames}`}`;
                    } else {
                        progressFrames.textContent = '';
                    }
                }

                // 预估剩余时间
                if (progressEta && data.progress > 0 && data.progress < 100) {
                    const elapsed = (Date.now() - startTime) / 1000;
                    const eta = (elapsed / data.progress) * (100 - data.progress);
                    progressEta.textContent = `ETA: ${formatDuration(eta)}`;
                }

                // 状态文本
                if (progressText) {
                    const statusTexts = {
                        pending: _I['status.pending'] || t('status.pending'),
                        processing: `${_I['restore.processing'] || t('restore.processing')} (${data.progress}%)`,
                    };
                    progressText.textContent = statusTexts[data.status] || (_I['restore.processing'] || t('restore.processing'));
                }

                // 任务完成
                if (data.status === 'completed') {
                    es.close();
                    currentRestoreEventSource = null;
                    if (progressText) progressText.textContent = _I['restore.completed'] || t('restore.completed');
                    if (progressEta) progressEta.textContent = '';
                    if (taskStatus) {
                        taskStatus.textContent = _I['status.completed'] || t('status.completed');
                        taskStatus.className = 'sv-badge sv-badge-completed';
                    }

                    // 显示结果
                    showRestoreResult(taskId, taskType || data.task_type);
                    toast(`${typeLabel}: ${_I['restore.completed'] || t('restore.completed')}`, 'success');
                }

                // 任务失败
                if (data.status === 'failed') {
                    es.close();
                    currentRestoreEventSource = null;
                    if (progressText) progressText.textContent = _I['restore.failed'] || t('restore.failed');
                    if (taskStatus) {
                        taskStatus.textContent = _I['status.failed'] || t('status.failed');
                        taskStatus.className = 'sv-badge sv-badge-failed';
                    }
                    toast(`${typeLabel}: ${_I['restore.failed'] || t('restore.failed')}`, 'error');
                }
            } catch (err) {
                console.error('SSE data parse error:', err);
            }
        };

        es.onerror = () => {
            es.close();
            currentRestoreEventSource = null;
            toast(_I['system.connection_failed'] || t('system.connection_failed'), 'warning');
        };
    }

    function showRestoreResult(taskId, taskType) {
        const progressCard = document.getElementById('progressCard');
        const resultCard = document.getElementById('resultCard');
        const resultVideo = document.getElementById('resultVideo');
        const btnDownload = document.getElementById('btnDownload');

        if (progressCard) progressCard.style.display = 'none';
        if (resultCard) resultCard.style.display = 'block';
        if (btnDownload) btnDownload.href = `/api/restore/${taskId}/download`;

        if (taskType === 'video') {
            if (resultVideo) resultVideo.src = `/api/restore/${taskId}/download`;
        } else {
            const compareCard = document.getElementById('compareCard');
            const beforeSrc = document.getElementById('imagePreview')?.src || '';
            const afterSrc = `/api/restore/${taskId}/download`;
            if (compareCard) compareCard.style.display = 'block';
            const compareBefore = document.getElementById('compareBefore');
            const compareAfterImg = document.getElementById('compareAfterImg');
            if (compareBefore) compareBefore.src = beforeSrc;
            if (compareAfterImg) compareAfterImg.src = afterSrc;
            initCompareSlider('compareContainer', 'compareSlider', 'compareAfter');
        }
    }

    async function cancelRestoreTask(taskId) {
        try {
            await api.post(`/api/restore/${taskId}/cancel`, {});
            toast(t('task.canceled'), 'info');
        } catch (err) {
            toast((t('task.cancel_failed') + ': ' + err.message), 'error');
        }
    }

    // ===== 前后对比滑块 =====
    function initCompareSlider(containerId, sliderId, afterId) {
        const container = document.getElementById(containerId);
        const slider = document.getElementById(sliderId);
        const afterEl = document.getElementById(afterId);

        if (!container || !slider || !afterEl) return;

        let isDragging = false;
        let dragAbortController = null;

        function updatePosition(x) {
            const rect = container.getBoundingClientRect();
            let pos = (x - rect.left) / rect.width;
            pos = Math.max(0, Math.min(1, pos));

            slider.style.transform = `translateX(${pos * rect.width}px)`;
            afterEl.style.clipPath = `inset(0 0 0 ${pos * 100}%)`;
        }

        // 初始位置 50%
        updatePosition(container.getBoundingClientRect().left + container.getBoundingClientRect().width / 2);

        function startDrag() {
            isDragging = true;
            slider.style.willChange = 'transform';
            // 终止之前的拖拽监听器
            if (dragAbortController) {
                dragAbortController.abort();
            }
            dragAbortController = new AbortController();
            const signal = dragAbortController.signal;

            document.addEventListener('mousemove', (e) => {
                if (isDragging) {
                    e.preventDefault();
                    updatePosition(e.clientX);
                }
            }, { signal });

            document.addEventListener('mouseup', () => {
                isDragging = false;
                slider.style.willChange = '';
                dragAbortController.abort();
                dragAbortController = null;
            }, { signal });

            document.addEventListener('touchmove', (e) => {
                if (isDragging) {
                    updatePosition(e.touches[0].clientX);
                }
            }, { signal });

            document.addEventListener('touchend', () => {
                isDragging = false;
                slider.style.willChange = '';
                dragAbortController.abort();
                dragAbortController = null;
            }, { signal });
        }

        container.addEventListener('mousedown', (e) => {
            startDrag();
            updatePosition(e.clientX);
        });

        // 触摸支持
        container.addEventListener('touchstart', (e) => {
            startDrag();
            updatePosition(e.touches[0].clientX);
        });
    }

    // ===== 设置页面 =====
    function switchSettingsTab(el, sectionName) {
        // 更新导航高亮和 ARIA
        document.querySelectorAll('#settingsNav .nav-item').forEach(item => {
            item.classList.remove('active');
            item.setAttribute('aria-selected', 'false');
            item.setAttribute('tabindex', '-1');
        });
        el.classList.add('active');
        el.setAttribute('aria-selected', 'true');
        el.setAttribute('tabindex', '0');

        // 切换内容区
        document.querySelectorAll('.sv-settings-section').forEach(section => {
            section.style.display = 'none';
        });
        const target = document.getElementById(`section-${sectionName}`);
        if (target) target.style.display = 'block';
    }

    function initSettingsTabKeyboardNav() {
        const tablist = document.getElementById('settingsNav');
        if (!tablist) return;

        const tabs = tablist.querySelectorAll('[role="tab"]');
        if (tabs.length === 0) return;

        tablist.addEventListener('keydown', (e) => {
            const currentTab = e.target.closest('[role="tab"]');
            if (!currentTab) return;

            const tabArray = Array.from(tabs);
            const currentIndex = tabArray.indexOf(currentTab);
            let newIndex;

            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                e.preventDefault();
                newIndex = (currentIndex + 1) % tabArray.length;
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                e.preventDefault();
                newIndex = (currentIndex - 1 + tabArray.length) % tabArray.length;
            } else if (e.key === 'Home') {
                e.preventDefault();
                newIndex = 0;
            } else if (e.key === 'End') {
                e.preventDefault();
                newIndex = tabArray.length - 1;
            } else if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                currentTab.click();
                return;
            } else {
                return;
            }

            tabArray[newIndex].focus();
            tabArray[newIndex].click();
        });
    }

    async function loadSettings() {
        try {
            const settings = await api.get('/api/system/settings');

            if (settings.model) {
                const modelSize = document.getElementById('defaultModelSize');
                if (modelSize) modelSize.value = settings.model.default_size || '3b';

                const modelPrecision = document.getElementById('modelPrecision');
                if (modelPrecision) modelPrecision.value = settings.model.precision || 'fp16';

                const autoLoad = document.getElementById('autoLoad');
                if (autoLoad) autoLoad.checked = settings.model.auto_load !== false;
            }

            if (settings.gpu) {
                const gpuBackend = document.getElementById('gpuBackend');
                if (gpuBackend) gpuBackend.value = settings.gpu.backend || 'auto';

                const memoryStrategy = document.getElementById('memoryStrategy');
                if (memoryStrategy) memoryStrategy.value = settings.gpu.memory_strategy || 'balanced';

                const enableFp16 = document.getElementById('enableFp16');
                if (enableFp16) enableFp16.checked = settings.gpu.enable_fp16 !== false;
            }

            if (settings.i18n) {
                const locale = document.getElementById('locale');
                if (locale) locale.value = settings.i18n.default_locale || 'zh';
            }
        } catch (err) {
            console.error('加载设置失败:', err);
        }
    }

    // ===== 历史记录 =====
    async function deleteHistoryRecord(id) {
        confirm('删除记录', '确定要删除此记录吗？', async () => {
            try {
                await api.delete(`/api/system/history/${id}`);
                toast('记录已删除', 'success');
                // 触发刷新
                const btnRefresh = document.getElementById('btnRefresh');
                if (btnRefresh) btnRefresh.click();
            } catch (err) {
                toast('删除失败: ' + err.message, 'error');
            }
        });
    }

    // ===== 重置修复页面 =====
    function resetRestore() {
        const progressCard = document.getElementById('progressCard');
        const resultCard = document.getElementById('resultCard');
        const compareCard = document.getElementById('compareCard');
        const batchProgressCard = document.getElementById('batchProgressCard');
        const uploadZone = document.getElementById('restoreUploadZone');
        const fileInput = document.getElementById('restoreFileInput');
        const fileInfo = document.getElementById('restoreFileInfo');
        const imagePreview = document.getElementById('imagePreview');
        const resultVideo = document.getElementById('resultVideo');
        const folderPath = document.getElementById('folderPath');
        const folderScanResults = document.getElementById('folderScanResults');

        if (progressCard) progressCard.style.display = 'none';
        if (resultCard) resultCard.style.display = 'none';
        if (compareCard) compareCard.style.display = 'none';
        if (batchProgressCard) batchProgressCard.style.display = 'none';
        if (uploadZone) uploadZone.classList.remove('has-file');
        if (fileInput) fileInput.value = '';
        if (fileInfo) {
            fileInfo.style.display = 'none';
            fileInfo.textContent = '';
        }
        if (imagePreview) {
            imagePreview.style.display = 'none';
            imagePreview.src = '';
        }
        if (resultVideo) {
            resultVideo.style.display = 'none';
            resultVideo.src = '';
        }
        if (folderPath) folderPath.value = '';
        if (folderScanResults) folderScanResults.innerHTML = '';

        // 重置进度条
        const progressBar = document.getElementById('progressBar');
        if (progressBar) {
            progressBar.style.width = '0%';
            progressBar.classList.add('animated');
            progressBar.classList.remove('bg-success');
            progressBar.classList.add('bg-primary');
            progressBar.setAttribute('aria-valuenow', '0');
        }

        // 关闭 SSE
        if (currentRestoreEventSource) {
            currentRestoreEventSource.close();
            currentRestoreEventSource = null;
        }
    }

    // ===== 工具函数 =====
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    function formatTimestamp(isoString) {
        if (!isoString) return '--';
        try {
            const date = new Date(isoString);
            const localeMap = { zh: 'zh-CN', en: 'en-US', ja: 'ja-JP', fr: 'fr-FR' };
            const currentLocale = window.__LOCALE__ || 'zh';
            return date.toLocaleString(localeMap[currentLocale] || 'zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            });
        } catch {
            return isoString;
        }
    }

    function formatUptime(seconds) {
        if (!seconds || seconds < 0) return '--';
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);

        const parts = [];
        if (days > 0) parts.push(`${days}${t('time.day')}`);
        if (hours > 0) parts.push(`${hours}${t('time.hour')}`);
        if (mins > 0) parts.push(`${mins}${t('time.minute')}`);
        parts.push(`${secs}${t('time.second')}`);
        return parts.join(' ');
    }

    function formatDuration(seconds) {
        if (seconds < 60) return `${Math.round(seconds)}${t('time.second')}`;
        if (seconds < 3600) return `${Math.round(seconds / 60)}${t('time.minute')}`;
        return `${(seconds / 3600).toFixed(1)}${t('time.hour')}`;
    }

    // ===== 语言切换下拉菜单 =====
    const LOCALE_ORDER = ['zh', 'en', 'ja', 'fr'];

    async function switchLocale(localeCode) {
        try {
            const data = await api.post('/api/system/locale', { locale: localeCode });
            toast(data.message || t('locale.switched'), 'success');
            // 刷新当前页面以应用新语言
            setTimeout(() => window.location.reload(), 500);
        } catch (err) {
            toast((t('locale.switch_failed') + ': ' + err.message), 'error');
        }
    }

    // ===== 历史记录右键菜单 =====
    let _contextMenuRecordId = null;
    let _contextMenuOutputPath = null;

    function showRowContextMenu(event, row) {
        event.preventDefault();
        const menu = document.getElementById('svContextMenu');
        if (!menu) return;

        _contextMenuRecordId = row.dataset.recordId;
        _contextMenuOutputPath = row.dataset.output;

        const openBtn = document.getElementById('ctxOpenOutputDir');
        if (openBtn) {
            openBtn.disabled = !_contextMenuOutputPath;
        }

        menu.style.left = `${event.clientX}px`;
        menu.style.top = `${event.clientY}px`;
        menu.classList.add('show');
        menu.setAttribute('aria-hidden', 'false');
    }

    function closeContextMenu() {
        const menu = document.getElementById('svContextMenu');
        if (menu) {
            menu.classList.remove('show');
            menu.setAttribute('aria-hidden', 'true');
        }
    }

    function getOutputDir(path) {
        if (!path) return '';
        const normalized = path.replace(/\\/g, '/');
        const lastSlash = normalized.lastIndexOf('/');
        return lastSlash > 0 ? normalized.substring(0, lastSlash) : normalized;
    }

    // ===== 初始化 =====
    function init() {
        // 初始化主题
        initTheme();

        // 初始化全局 SSE 连接
        initGlobalSSE();

        // 初始化语言切换下拉菜单
        initLocaleDropdown();

        // HTMX 全局错误联动 Toast
        if (typeof htmx !== 'undefined') {
            document.body.addEventListener('htmx:responseError', (evt) => {
                const xhr = evt.detail.xhr;
                let msg = `${t('error.request_failed')} (${xhr.status})`;
                try {
                    const data = JSON.parse(xhr.responseText);
                    msg = data.error?.message || data.detail || msg;
                } catch {}
                toast(msg, 'error');
            });

            document.body.addEventListener('htmx:sendError', (evt) => {
                const error = evt.detail.error;
                toast(`${t('error.send_failed')}: ${error?.message || t('error.network_error')}`, 'error');
            });

            // 后端通过 HX-Trigger: showToast 触发的事件
            document.body.addEventListener('showToast', (evt) => {
                if (evt.detail) {
                    toast(evt.detail.message, evt.detail.type || 'info');
                }
            });
        }

        // 高亮当前导航
        const currentPath = window.location.pathname;
        document.querySelectorAll('.sv-nav-link').forEach(link => {
            const href = link.getAttribute('href');
            if (href === currentPath) {
                link.classList.add('active');
            }
        });

        // 移动端导航切换
        const btnToggleNav = document.getElementById('btnToggleNav');
        const mainNav = document.getElementById('mainNav');
        const mobileNavOverlay = document.getElementById('mobileNavOverlay');
        if (btnToggleNav && mainNav) {
            function closeMobileNav() {
                mainNav.classList.remove('show');
                if (mobileNavOverlay) mobileNavOverlay.classList.remove('show');
            }

            function toggleMobileNav() {
                const isOpen = mainNav.classList.toggle('show');
                if (mobileNavOverlay) {
                    mobileNavOverlay.classList.toggle('show', isOpen);
                }
            }

            btnToggleNav.addEventListener('click', toggleMobileNav);

            if (mobileNavOverlay) {
                mobileNavOverlay.addEventListener('click', closeMobileNav);
            }

            mainNav.querySelectorAll('.sv-nav-link').forEach(link => {
                link.addEventListener('click', closeMobileNav);
            });

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && mainNav.classList.contains('show')) {
                    closeMobileNav();
                }
            });
        }

        // 历史记录右键菜单交互
        const contextMenu = document.getElementById('svContextMenu');
        if (contextMenu) {
            document.addEventListener('click', (e) => {
                if (!contextMenu.contains(e.target)) closeContextMenu();
            });

            document.getElementById('ctxOpenOutputDir').addEventListener('click', async () => {
                const dir = getOutputDir(_contextMenuOutputPath);
                if (!dir) return;
                try {
                    await api.post('/api/system/open-explorer', { path: dir });
                    toast(t('dir.opened'), 'success');
                } catch (err) {
                    toast(t('dir.open_failed') + ': ' + err.message, 'error');
                }
                closeContextMenu();
            });

            document.getElementById('ctxRefreshRow').addEventListener('click', () => {
                const btnRefresh = document.getElementById('btnRefresh');
                if (btnRefresh) btnRefresh.click();
                closeContextMenu();
            });

            document.getElementById('ctxDeleteRecord').addEventListener('click', () => {
                closeContextMenu();
                if (!_contextMenuRecordId) return;
                confirm(t('common.confirm') || 'Confirm', t('history.delete_confirm') || 'Delete this record?', async () => {
                    try {
                        await api.delete(`/api/system/history/${_contextMenuRecordId}`);
                        toast(t('history.record_deleted') || 'Record deleted', 'success');
                        const btnRefresh = document.getElementById('btnRefresh');
                        if (btnRefresh) btnRefresh.click();
                    } catch (err) {
                        toast(t('common.delete') + ' ' + t('error.default') + ': ' + err.message, 'error');
                    }
                });
            });
        }

        // 点击模态框外部关闭（带退出动画）
        document.querySelectorAll('.sv-modal-overlay').forEach(overlay => {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    closeModal(overlay.id);
                }
            });
        });

        // ESC 关闭模态框与右键菜单
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.sv-modal-overlay.show').forEach(modal => {
                    closeModal(modal.id);
                });
                closeContextMenu();
            }
        });

        // Data attribute modal close buttons
        document.querySelectorAll('[data-modal-close]').forEach(btn => {
            btn.addEventListener('click', () => {
                const modalId = btn.getAttribute('data-modal-close');
                closeModal(modalId);
            });
        });

        // 键盘快捷键：Alt+数字 直达导航
        // 不使用 Ctrl+数字（浏览器标签页切换冲突）
        // Alt+数字 在键盘上横向连续，手部移动距离最短
        // 注意：Windows 下 Alt 键会激活菜单栏，需在 keydown 阶段阻止默认行为
        const NAV_SHORTCUTS = {
            '1': { path: '/', label: '首页' },
            '2': { path: '/restore', label: '修复' },
            '3': { path: '/history', label: '历史记录' },
            '4': { path: '/settings', label: '设置' },
        };

        function isInputFocused() {
            const el = document.activeElement;
            if (!el) return false;
            const tag = el.tagName;
            return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
        }

        // 在 keydown 阶段阻止 Alt 键激活菜单栏，并处理快捷键
        document.addEventListener('keydown', (e) => {
            if (!e.altKey || e.ctrlKey || e.shiftKey || e.metaKey) return;
            if (isInputFocused()) return;

            const key = e.key.toLowerCase();
            const shortcut = NAV_SHORTCUTS[key];
            if (shortcut) {
                e.preventDefault();
                e.stopPropagation();
                window.location.href = shortcut.path;
            }
        }, true); // 使用捕获阶段，优先于浏览器默认处理

        // 更新 Widget 内存进度条
        async function updateWidgetMemory() {
            try {
                const health = await api.get('/api/system/health');
                if (health.system && health.system.memory_total_gb > 0) {
                    const total = health.system.memory_total_gb;
                    const avail = health.system.memory_available_gb;
                    const usedPct = Math.round(((total - avail) / total) * 100);
                    const fillEl = document.getElementById('statusMemFill');
                    const textEl = document.getElementById('statusMemText');
                    if (fillEl) fillEl.style.width = usedPct + '%';
                    if (textEl) textEl.textContent = usedPct + '%';
                }
            } catch (e) { /* ignore */ }
        }
        updateWidgetMemory();

        // 定期更新状态栏时间（i18n 格式）
        const localeMap = { zh: 'zh-CN', en: 'en-US', ja: 'ja-JP', fr: 'fr-FR' };
        const _statusTimeInterval = setInterval(() => {
            const statusTime = document.getElementById('statusTime');
            if (statusTime) {
                const currentLocale = window.__LOCALE__ || 'zh';
                statusTime.textContent = new Date().toLocaleTimeString(localeMap[currentLocale] || 'zh-CN');
            }
        }, 1000);

        window.addEventListener('beforeunload', () => {
            clearInterval(_statusTimeInterval);
        });

        // 表单验证 (P0-4)
        initFormValidation();

        // Shrink 参数联动
        initShrinkToggle();

        // 设置页面 Tab 键盘导航
        initSettingsTabKeyboardNav();

        // 移动端参数面板折叠 (P4-4)
        if (window.matchMedia('(max-width: 768px)').matches) {
            document.querySelectorAll('.sv-restore-params .sv-card .sv-card-header, .sv-workflow-panel .sv-workflow-node .node-header').forEach(header => {
                header.addEventListener('click', () => {
                    const card = header.closest('.sv-card, .sv-workflow-node');
                    if (card) card.classList.toggle('expanded');
                });
            });
        }
    }

    // ===== 语言切换下拉菜单 =====
    function initLocaleDropdown() {
        const btn = document.getElementById('btnLocaleSwitch');
        const menu = document.getElementById('localeMenu');
        const dropdown = document.getElementById('localeDropdown');

        if (!btn || !menu || !dropdown) return;

        // 点击按钮切换菜单
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = menu.classList.toggle('show');
            btn.setAttribute('aria-expanded', isOpen.toString());
        });

        // 点击菜单项切换语言
        menu.querySelectorAll('.sv-locale-item').forEach(item => {
            item.addEventListener('click', async () => {
                const locale = item.dataset.locale;
                if (locale) {
                    await switchLocale(locale);
                    menu.classList.remove('show');
                    btn.setAttribute('aria-expanded', 'false');
                }
            });
        });

        // 点击外部关闭菜单
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target)) {
                menu.classList.remove('show');
                btn.setAttribute('aria-expanded', 'false');
            }
        });

        // ESC 关闭菜单
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && menu.classList.contains('show')) {
                menu.classList.remove('show');
                btn.setAttribute('aria-expanded', 'false');
                btn.focus();
            }
        });
    }

    // ===== 主题管理 =====
    function initTheme() {
        const saved = localStorage.getItem('sv-theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const theme = saved || (prefersDark ? 'dark' : 'light');
        applyTheme(theme);

        const btn = document.getElementById('btnThemeToggle');
        if (btn) {
            btn.addEventListener('click', () => {
                const current = document.documentElement.getAttribute('data-theme') || 'dark';
                const next = current === 'dark' ? 'light' : 'dark';
                applyTheme(next);
                localStorage.setItem('sv-theme', next);
            });
        }
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        const icon = document.getElementById('themeIcon');
        if (icon) {
            icon.className = theme === 'dark' ? 'bi bi-moon-stars-fill' : 'bi bi-sun-fill';
        }
    }

    // ===== Shrink 参数联动 =====
    function initShrinkToggle() {
        const shrinkEnabled = document.getElementById('shrink_enabled');
        const shrinkAlgorithm = document.getElementById('shrink_algorithm');
        const shrinkScale = document.getElementById('shrink_scale');

        if (!shrinkEnabled || !shrinkAlgorithm) return;

        // 初始化状态：根据 checkbox 状态设置 disabled
        const updateShrinkState = () => {
            const enabled = shrinkEnabled.checked;
            shrinkAlgorithm.disabled = !enabled;
            if (shrinkScale) shrinkScale.disabled = !enabled;
        };

        // 初始设置
        updateShrinkState();

        // 监听变化
        shrinkEnabled.addEventListener('change', updateShrinkState);
    }

    // ===== 表单验证 (P0-4) =====
    function initFormValidation() {
        document.querySelectorAll('input[type="number"].sv-form-control').forEach(input => {
            const min = parseFloat(input.min);
            const max = parseFloat(input.max);

            if (isNaN(min) && isNaN(max)) return;

            // 添加错误提示元素
            let errorEl = input.parentElement.querySelector('.sv-form-error');
            if (!errorEl) {
                errorEl = document.createElement('div');
                errorEl.className = 'sv-form-error';
                input.parentElement.appendChild(errorEl);
            }

            input.addEventListener('input', () => {
                const val = parseFloat(input.value);
                const group = input.closest('.sv-form-group');

                if (input.value === '') {
                    input.classList.remove('is-invalid');
                    if (group) group.classList.remove('has-error');
                    return;
                }

                let errorMsg = '';
                if (!isNaN(min) && val < min) {
                    errorMsg = `最小值为 ${min}`;
                }
                if (!isNaN(max) && val > max) {
                    errorMsg = `最大值为 ${max}`;
                }

                if (errorMsg) {
                    input.classList.add('is-invalid');
                    if (group) group.classList.add('has-error');
                    errorEl.textContent = errorMsg;
                } else {
                    input.classList.remove('is-invalid');
                    if (group) group.classList.remove('has-error');
                }
            });
        });
    }

    // DOM 加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // ===== 目录浏览器 =====
    let _dirBrowserCallback = null;

    function openDirBrowser(currentPath, callback) {
        _dirBrowserCallback = callback;
        const pathInput = document.getElementById('dirBrowserPathInput');
        pathInput.value = currentPath || '';
        SeedVR2.openModal('dirBrowserModal');
        loadDirListing(currentPath || '');

        // Go 按钮
        document.getElementById('dirBrowserGoBtn').onclick = () => {
            loadDirListing(pathInput.value.trim());
        };
        // 打开资源管理器按钮
        document.getElementById('dirBrowserOpenExplorerBtn').onclick = async () => {
            const p = pathInput.value.trim();
            if (!p) { SeedVR2.toast(t('dir.enter_path'), 'warning'); return; }
            try {
                await SeedVR2.api.post('/api/system/open-explorer', { path: p });
                SeedVR2.toast(t('dir.opened'), 'success');
            } catch (err) {
                SeedVR2.toast(t('dir.open_failed') + ': ' + err.message, 'error');
            }
        };
        // Enter 键
        pathInput.onkeydown = (e) => {
            if (e.key === 'Enter') loadDirListing(pathInput.value.trim());
        };
        // 选择按钮
        document.getElementById('dirBrowserSelectBtn').onclick = () => {
            const selected = pathInput.value.trim();
            if (selected && _dirBrowserCallback) {
                _dirBrowserCallback(selected);
            }
            SeedVR2.closeModal('dirBrowserModal');
        };
    }

    async function loadDirListing(path) {
        const listEl = document.getElementById('dirBrowserList');
        const pathInput = document.getElementById('dirBrowserPathInput');

        // 清空并显示加载状态
        listEl.innerHTML = '';
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'sv-dir-loading';
        const spinner = document.createElement('span');
        spinner.className = 'sv-spinner sv-dir-spinner';
        loadingDiv.appendChild(spinner);
        const loadingText = document.createElement('span');
        loadingText.textContent = t('dir.loading');
        loadingDiv.appendChild(loadingText);
        listEl.appendChild(loadingDiv);

        try {
            const url = `/api/system/browse-dir?path=${encodeURIComponent(path)}`;
            const response = await fetch(url);
            if (!response.ok) {
                const err = await response.json().catch(() => ({ detail: 'Failed' }));
                listEl.innerHTML = '';
                const errorDiv = document.createElement('div');
                errorDiv.className = 'sv-dir-error';
                errorDiv.textContent = err.detail || t('dir.error');
                listEl.appendChild(errorDiv);
                return;
            }
            const data = await response.json();
            pathInput.value = data.current_path || path;

            // 清空列表
            listEl.innerHTML = '';
            let hasItems = false;

            // 父目录
            if (data.parent_path !== undefined && data.parent_path !== data.current_path) {
                hasItems = true;
                const itemDiv = document.createElement('div');
                itemDiv.className = 'dir-item sv-dir-item';
                itemDiv.dataset.path = data.parent_path || '';

                const icon = document.createElement('i');
                icon.className = 'bi bi-arrow-up-circle sv-text-muted';

                const nameSpan = document.createElement('span');
                nameSpan.className = 'sv-text-secondary';
                nameSpan.textContent = '..';

                itemDiv.appendChild(icon);
                itemDiv.appendChild(nameSpan);

                itemDiv.addEventListener('click', () => {
                    loadDirListing(itemDiv.dataset.path);
                });

                listEl.appendChild(itemDiv);
            }

            // 项目列表
            for (const item of data.items) {
                hasItems = true;
                const iconClass = item.type === 'drive' ? 'bi-hdd' : 'bi-folder-fill';
                const iconColorClass = item.type === 'drive' ? 'sv-text-muted' : 'sv-text-warning';

                const itemDiv = document.createElement('div');
                itemDiv.className = 'dir-item sv-dir-item';
                itemDiv.dataset.path = item.path;

                const icon = document.createElement('i');
                icon.className = `bi ${iconClass} ${iconColorClass}`;

                const nameSpan = document.createElement('span');
                nameSpan.className = 'sv-text-primary';
                nameSpan.textContent = item.name;

                itemDiv.appendChild(icon);
                itemDiv.appendChild(nameSpan);

                itemDiv.addEventListener('click', () => {
                    loadDirListing(itemDiv.dataset.path);
                });

                listEl.appendChild(itemDiv);
            }

            if (!hasItems) {
                const emptyDiv = document.createElement('div');
                emptyDiv.className = 'sv-dir-empty';
                emptyDiv.textContent = t('dir.empty');
                listEl.appendChild(emptyDiv);
            }
        } catch (err) {
            listEl.innerHTML = '';
            const errorDiv = document.createElement('div');
            errorDiv.className = 'sv-dir-error';
            errorDiv.textContent = err.message;
            listEl.appendChild(errorDiv);
        }
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ===== 卡片显示/隐藏动画 =====
    function showCard(elementId) {
        const el = document.getElementById(elementId);
        if (!el) return;
        el.style.display = 'block';
        el.classList.add('sv-fade-in');
        setTimeout(() => el.classList.remove('sv-fade-in'), 300);
    }

    function hideCard(elementId) {
        const el = document.getElementById(elementId);
        if (!el) return;
        el.style.display = 'none';
    }

    // ===== 公开 API =====
    return {
        api,
        t,
        httpStatusText,
        parseApiError,
        toast,
        confirm,
        closeModal,
        openModal,
        setupUploadZone,
        startRestoreProgressSSE,
        cancelRestoreTask,
        resetRestore,
        initCompareSlider,
        switchSettingsTab,
        loadSettings,
        deleteHistoryRecord,
        cycleLocale: switchLocale,
        switchLocale,
        showRowContextMenu,
        openDirBrowser,
        showCard,
        hideCard,
        formatFileSize,
        formatTimestamp,
        formatUptime,
        formatDuration,
        initTheme,
        applyTheme,
        escapeHtml,
        initFormValidation,
        getCsrfToken,
        csrfHeaders,
    };
})();
