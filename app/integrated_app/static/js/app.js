/**
 * @file SeedVR2 - 前端交互脚本
 * @project SeedVR2 - AI视频/图像修复系统
 * @description 包含完整的前端交互逻辑，为SeedVR2视频/图像修复系统提供用户界面支持
 * @module SeedVR2
 * @version 2.0.0
 * @author SeedVR2 Team
 *
 * @description 功能列表：
 * - i18n多语言翻译（中文/英文/日文/法文）
 * - HTTP API请求封装（GET/POST/DELETE/文件上传）
 * - CSRF Token安全防护
 * - SSE服务器推送事件连接（全局状态、修复进度实时更新）
 * - 前后对比滑块（支持鼠标/触摸拖拽）
 * - Toast通知系统（支持多种类型、错误详情展开、重试操作）
 * - 模态框系统（焦点陷阱、键盘导航、动画效果）
 * - 文件上传区域（点击选择、拖拽上传）
 * - 目录浏览器（文件系统导航、资源管理器打开）
 * - 系统状态栏（GPU状态、模型状态、内存使用、实时时钟）
 * - 主题切换（暗色/亮色主题持久化）
 * - 表单验证（数值范围、错误提示）
 * - 历史记录管理（右键菜单、删除确认）
 * - 导航快捷键（Alt+数字键直达）
 * - 移动端响应式导航
 * - 用户偏好持久化
 * - 参数预设与推荐
 * - Shrink参数联动控制
 * - 设置页面Tab键盘导航
 *
 * @dependencies 核心依赖：
 * - 原生浏览器API（Fetch API, EventSource, AbortController, DataTransfer）
 * - Bootstrap Icons（图标库，用于Toast、按钮、导航等UI元素）
 * - HTMX（HTML增强库，通过事件监听进行错误处理与Toast联动）
 * - 浏览器LocalStorage（主题、用户偏好持久化）
 * - CSS自定义属性（主题色、动画、响应式布局）
 * - CSS Transitions/Animations（模态框、Toast、卡片淡入淡出动画）
 */

const SeedVR2 = (() => {
    'use strict';

    // ===== 客户端 i18n =====
    /**
     * @constant {Object} _translations
     * @description 多语言翻译字典，支持中文(zh)、繁体中文(zh-TW)、英文(en)、日文(ja)、法文(fr)五种语言
     * @property {Object} zh - 中文翻译
     * @property {Object} en - 英文翻译
     * @property {Object} ja - 日文翻译
     * @property {Object} fr - 法文翻译
     * @private
     */
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
            'error.action_retry': '重试',
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
            'form.min_value': '最小值为 {min}',
            'form.max_value': '最大值为 {max}',
            'system.connection_failed': '连接失败',
            'system.reconnected': '已重新连接',
            'history.video': '视频',
            'history.image': '图像',
            'video.batch_current_processing': '当前处理: {current}/{total}',
            'restore.stage_encoding': '编码阶段',
            'restore.stage_denoising': '去噪阶段',
            'restore.stage_decoding': '解码阶段',
            'status.pending': '等待中',
            'restore.processing': '处理中...',
            'restore.completed': '修复完成',
            'restore.failed': '修复失败',
            'status.completed': '已完成',
            'status.failed': '失败',
            'common.confirm': '确认',
            'history.delete_confirm': '确定要删除此记录吗？',
            'common.delete': '删除',
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
            'error.action_retry': 'Retry',
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
            'form.min_value': 'Minimum value is {min}',
            'form.max_value': 'Maximum value is {max}',
            'system.connection_failed': 'Connection failed',
            'system.reconnected': 'Reconnected',
            'history.video': 'Video',
            'history.image': 'Image',
            'video.batch_current_processing': 'Processing: {current}/{total}',
            'restore.stage_encoding': 'Encoding',
            'restore.stage_denoising': 'Denoising',
            'restore.stage_decoding': 'Decoding',
            'status.pending': 'Pending',
            'restore.processing': 'Processing...',
            'restore.completed': 'Restore completed',
            'restore.failed': 'Restore failed',
            'status.completed': 'Completed',
            'status.failed': 'Failed',
            'common.confirm': 'Confirm',
            'history.delete_confirm': 'Delete this record?',
            'common.delete': 'Delete',
        },
        ja: {
            'error.400': 'リクエストパラメータが無効です',
            'error.401': '先にログインしてください',
            'error.403': '権限がありません',
            'error.404': 'リソースが見つかりません',
            'error.408': 'リクエストがタイムアウトしました。再試行してください',
            'error.409': '操作が競合しています。更新して再試行してください',
            'error.422': 'データ形式が無効です',
            'error.429': 'リクエストが多すぎます。しばらく待ってから再試行してください',
            'error.500': 'サーバー内部エラー。しばらく待ってから再試行してください',
            'error.502': 'サービスが一時的に利用できません',
            'error.503': 'サービスがメンテナンス中です',
            'error.504': 'リクエストがタイムアウトしました。再試行してください',
            'error.default': 'リクエストに失敗しました',
            'error.request_failed': 'リクエストに失敗しました',
            'error.send_failed': 'リクエストの送信に失敗しました',
            'error.network_error': 'ネットワークエラー',
            'error.action_retry': '再試行',
            'dir.empty': '空のディレクトリ',
            'dir.enter_path': 'パスを入力してください',
            'dir.opened': 'ファイルエクスプローラーで開きました',
            'dir.open_failed': '開けませんでした',
            'dir.loading': '読み込み中...',
            'dir.error': '読み込みに失敗しました',
            'time.day': '日',
            'time.hour': '時間',
            'time.minute': '分',
            'time.second': '秒',
            'task.canceled': 'タスクがキャンセルされました',
            'task.cancel_failed': 'キャンセルに失敗しました',
            'history.delete_confirm_title': '記録を削除',
            'history.delete_confirm_msg': 'この記録を削除してもよろしいですか？',
            'history.record_deleted': '記録が削除されました',
            'history.delete_failed': '削除に失敗しました',
            'locale.switched': '言語が切り替わりました',
            'locale.switch_failed': '言語の切り替えに失敗しました',
            'form.min_value': '最小値は {min} です',
            'form.max_value': '最大値は {max} です',
            'system.connection_failed': '接続に失敗しました',
            'system.reconnected': '再接続しました',
            'history.video': '動画',
            'history.image': '画像',
            'video.batch_current_processing': '現在の処理: {current}/{total}',
            'restore.stage_encoding': 'エンコード中',
            'restore.stage_denoising': 'デノイズ中',
            'restore.stage_decoding': 'デコード中',
            'status.pending': '待機中',
            'restore.processing': '処理中...',
            'restore.completed': '修復完了',
            'restore.failed': '修復失敗',
            'status.completed': '完了',
            'status.failed': '失敗',
            'common.confirm': '確認',
            'history.delete_confirm': 'この記録を削除しますか？',
            'common.delete': '削除',
        },
        fr: {
            'error.400': 'Paramètres de requête invalides',
            'error.401': 'Veuillez vous connecter d\'abord',
            'error.403': 'Permission refusée',
            'error.404': 'Ressource non trouvée',
            'error.408': 'Délai d\'attente dépassé, veuillez réessayer',
            'error.409': 'Conflit, veuillez actualiser et réessayer',
            'error.422': 'Format de données invalide',
            'error.429': 'Trop de requêtes, veuillez réessayer plus tard',
            'error.500': 'Erreur interne du serveur, veuillez réessayer plus tard',
            'error.502': 'Service temporairement indisponible',
            'error.503': 'Service en maintenance',
            'error.504': 'Délai d\'attente dépassé, veuillez réessayer',
            'error.default': 'Requête échouée',
            'error.request_failed': 'Requête échouée',
            'error.send_failed': 'Échec de l\'envoi de la requête',
            'error.network_error': 'Erreur réseau',
            'error.action_retry': 'Réessayer',
            'dir.empty': 'Répertoire vide',
            'dir.enter_path': 'Veuillez entrer un chemin',
            'dir.opened': 'Ouvert dans l\'explorateur de fichiers',
            'dir.open_failed': 'Échec de l\'ouverture',
            'dir.loading': 'Chargement...',
            'dir.error': 'Échec du chargement',
            'time.day': 'j',
            'time.hour': 'h',
            'time.minute': 'min',
            'time.second': 's',
            'task.canceled': 'Tâche annulée',
            'task.cancel_failed': 'Échec de l\'annulation',
            'history.delete_confirm_title': 'Supprimer l\'enregistrement',
            'history.delete_confirm_msg': 'Êtes-vous sûr de vouloir supprimer cet enregistrement ?',
            'history.record_deleted': 'Enregistrement supprimé',
            'history.delete_failed': 'Échec de la suppression',
            'locale.switched': 'Langue changée',
            'locale.switch_failed': 'Échec du changement de langue',
            'form.min_value': 'La valeur minimale est {min}',
            'form.max_value': 'La valeur maximale est {max}',
            'system.connection_failed': 'Connexion échouée',
            'system.reconnected': 'Reconnecté',
            'history.video': 'Vidéo',
            'history.image': 'Image',
            'video.batch_current_processing': 'Traitement: {current}/{total}',
            'restore.stage_encoding': 'Encodage',
            'restore.stage_denoising': 'Débruitage',
            'restore.stage_decoding': 'Décodage',
            'status.pending': 'En attente',
            'restore.processing': 'Traitement...',
            'restore.completed': 'Restauration terminée',
            'restore.failed': 'Échec de la restauration',
            'status.completed': 'Terminé',
            'status.failed': 'Échoué',
            'common.confirm': 'Confirmer',
            'history.delete_confirm': 'Supprimer cet enregistrement ?',
            'common.delete': 'Supprimer',
        }
    };

    /**
     * @function t
     * @description i18n翻译函数，支持占位符替换
     * @param {string} key - 翻译键名
     * @param {Object} [params] - 占位符参数对象，键为占位符名称，值为替换内容
     * @returns {string} 翻译后的文本，如果键不存在则返回键名本身
     * @example
     * // 返回 "最小值为 1"
     * t('form.min_value', {min: 1});
     */
    function t(key, params) {
        const locale = window.__LOCALE__ || 'zh';
        const dict = _translations[locale] || _translations.zh;
        let value = dict[key] || _translations.zh[key] || key;
        if (params && typeof value === 'string') {
            for (const [k, v] of Object.entries(params)) {
                value = value.replace(`{${k}}`, String(v));
            }
        }
        return value;
    }

    // ===== API 封装 =====
    /**
     * @function httpStatusText
     * @description 根据HTTP状态码获取对应的错误消息文本
     * @param {number} status - HTTP状态码
     * @returns {string} 本地化的错误消息文本
     */
    function httpStatusText(status) {
        return t(`error.${status}`) || `${t('error.default')} (${status})`;
    }

    /**
     * @function parseApiError
     * @description 解析API响应错误，优先从响应数据中提取错误消息，否则使用HTTP状态码对应的消息
     * @param {Response} response - Fetch API Response对象
     * @param {Object} data - 解析后的响应JSON数据
     * @returns {string} 错误消息文本
     */
    function parseApiError(response, data) {
        if (data?.error?.message) return data.error.message;
        if (data?.detail) return typeof data.detail === 'string' ? data.detail : httpStatusText(response.status);
        return httpStatusText(response.status);
    }

    // ===== CSRF Token Helper =====
    /**
     * @function getCsrfToken
     * @description 从Cookie中获取CSRF Token，用于防止跨站请求伪造攻击
     * @returns {string|null} CSRF Token值，如果不存在则返回null
     */
    function getCsrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
        return match ? decodeURIComponent(match[1]) : null;
    }

    /**
     * @function csrfHeaders
     * @description 构造包含CSRF Token的请求头对象
     * @returns {Object} 请求头对象，包含X-CSRF-Token字段（如果Token存在）
     */
    function csrfHeaders() {
        const token = getCsrfToken();
        return token ? { 'X-CSRF-Token': token } : {};
    }

    /**
     * @function ensureCsrfToken
     * @description 确保拿到 CSRF Token 后再发非安全请求。若 cookie 中尚无
     * csrf_token（如新会话 / 跨来源预览 / cookie 分区未同步等场景），先请求一个
     * 安全 GET，服务端 CSRF 中间件会在响应中 Set-Cookie 种下 token，避免上传时
     * token 缺失被 403 拦截。依旧是 Double-Submit Cookie，不降级安全性。
     * @returns {Promise<string|null>} 引导后的 CSRF Token 值
     */
    async function ensureCsrfToken() {
        let token = getCsrfToken();
        if (token) {
            return token;
        }
        // 安全方法 (GET) 会触发中间件种下 csrf_token cookie；用 no-store 防止拿到缓存页
        await fetch('/', { method: 'GET', credentials: 'same-origin', cache: 'no-store' });
        return getCsrfToken();
    }

    /**
     * @function csrfSafeFetch
     * @description 非安全请求的统一封装：自动携带 CSRF token 头；若被 403 拦截
     * （典型原因是浏览器里残留了一个失效的 csrf_token cookie），服务端会在 403
     * 响应里补发一个新 token，此处重新引导读取后自动重试一次，实现自愈。
     * @param {string} url - 请求 URL
     * @param {Object} [options] - fetch 选项（method/headers/body）
     * @returns {Promise<Response>} fetch 返回的 Response 对象
     */
    async function csrfSafeFetch(url, options = {}) {
        await ensureCsrfToken();
        for (let attempt = 0; attempt < 2; attempt++) {
            const headers = { ...(options.headers || {}), ...csrfHeaders() };
            const response = await fetch(url, { ...options, headers });
            if (response.status !== 403 || attempt === 1) {
                return response;
            }
            // 排空并关闭 403 响应体，释放连接；随后读取服务端补发的新 token 重试
            response.text().catch(() => {});
            await ensureCsrfToken();
        }
        return new Response(JSON.stringify({ error: 'CSRF token 验证失败' }), { status: 403 });
    }

    /**
     * @namespace api
     * @description HTTP API请求封装对象，提供统一的请求方法和错误处理
     */
    const api = {
        /**
         * @function api.get
         * @description 发送GET请求
         * @param {string} url - 请求URL
         * @returns {Promise<Object>} 解析后的JSON响应数据
         * @throws {Error} 请求失败时抛出包含错误消息的Error对象
         */
        async get(url) {
            const response = await fetch(url);
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(parseApiError(response, data));
            }
            return response.json();
        },

        /**
         * @function api.post
         * @description 发送POST请求（JSON格式）
         * @param {string} url - 请求URL
         * @param {Object} data - 要发送的JSON数据
         * @returns {Promise<Object>} 解析后的JSON响应数据
         * @throws {Error} 请求失败时抛出包含错误消息的Error对象
         */
        async post(url, data) {
            const isFormData = typeof FormData !== 'undefined' && data instanceof FormData;
            const headers = isFormData ? {} : { 'Content-Type': 'application/json' };
            const response = await csrfSafeFetch(url, {
                method: 'POST',
                headers,
                body: isFormData ? data : JSON.stringify(data),
            });
            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(parseApiError(response, errData));
            }
            return response.json();
        },

        /**
         * @function api.delete
         * @description 发送DELETE请求
         * @param {string} url - 请求URL
         * @returns {Promise<Object>} 解析后的JSON响应数据
         * @throws {Error} 请求失败时抛出包含错误消息的Error对象
         */
        async delete(url) {
            const response = await csrfSafeFetch(url, { method: 'DELETE' });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(parseApiError(response, data));
            }
            return response.json();
        },

        /**
         * @function api.uploadRestore
         * @description 上传修复文件（使用FormData格式，支持文件上传）
         * @param {FormData} formData - 包含文件和其他参数的FormData对象
         * @returns {Promise<Object>} 解析后的JSON响应数据，包含任务ID等信息
         * @throws {Error} 请求失败时抛出包含错误消息的Error对象
         */
        async uploadRestore(formData) {
            const response = await csrfSafeFetch('/api/restore', {
                method: 'POST',
                body: formData,
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(parseApiError(response, data));
            }
            return response.json();
        },

        /**
         * @function api.submitWithLoading
         * @description 提交异步操作时显示按钮加载状态，操作完成后自动恢复
         * @param {HTMLElement} btn - 按钮元素
         * @param {Promise} promise - 要执行的异步操作Promise
         * @param {Object} [options] - 配置选项
         * @param {string} [options.loadingHtml] - 加载中显示的HTML内容
         * @param {string} [options.loadingText] - 加载中显示的文本
         * @param {boolean} [options.restoreHtml=true] - 是否在完成后恢复原始HTML
         * @returns {Promise} 异步操作的结果
         */
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
    /**
     * @constant {number} MAX_TOASTS
     * @description 屏幕上同时显示的最大Toast通知数量，超过此数量时最早的Toast会自动关闭
     * @default 3
     */
    const MAX_TOASTS = 3;

    /**
     * @function toast
     * @description 显示Toast通知消息，支持多种类型、自动关闭、错误详情展开和重试操作
     * @param {string} message - 通知消息内容
     * @param {string} [type='info'] - 通知类型：success/error/warning/info
     * @param {number} [duration=4000] - 自动关闭延迟时间（毫秒）
     * @returns {void}
     */
    function toast(message, type = 'info', duration = 4000) {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        // 限制最大数量，超出时移除最早的通知
        if (container.children.length >= MAX_TOASTS) {
            const oldest = container.firstElementChild;
            if (oldest) oldest.remove();
        }

        const iconMap = {
            success: 'bi-check-circle-fill',
            error: 'bi-exclamation-circle-fill',
            warning: 'bi-exclamation-triangle-fill',
            info: 'bi-info-circle-fill',
        };

        // 错误类型行动建议映射
        const actionMap = {
            400: t('error.400'),
            401: t('error.401'),
            403: t('error.403'),
            404: t('error.404'),
            429: t('error.429'),
            500: t('error.500'),
            502: t('error.502'),
            503: t('error.503'),
        };

        const el = document.createElement('div');
        el.className = `sv-toast toast-${type}`;

        const iconEl = document.createElement('i');
        iconEl.className = `bi ${iconMap[type] || iconMap.info}`;

        const msgSpan = document.createElement('span');
        msgSpan.style.flex = '1';
        // 长错误消息采用概要+可展开详情的双层展示
        if (type === 'error' && message.length > 60) {
            const briefEnd = message.indexOf(':');
            if (briefEnd > 0 && briefEnd < 40) {
                const brief = message.substring(0, briefEnd);
                const detail = message.substring(briefEnd + 1).trim();
                msgSpan.innerHTML = `<span class="sv-toast-brief">${escapeHtml(brief)}</span><details class="sv-toast-details"><summary>${escapeHtml('查看详情')}</summary><div class="sv-toast-detail-wrap"><span class="sv-toast-detail-text">${escapeHtml(detail)}</span><button type="button" class="sv-toast-copy" title="${escapeHtml(t('common.copy') || '复制')}"><i class="bi bi-clipboard"></i></button></div></details>`;
                // 添加复制功能
                const copyBtn = msgSpan.querySelector('.sv-toast-copy');
                if (copyBtn) {
                    copyBtn.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        try {
                            navigator.clipboard.writeText(detail).then(() => {
                                copyBtn.innerHTML = '<i class="bi bi-check-lg"></i>';
                                setTimeout(() => { copyBtn.innerHTML = '<i class="bi bi-clipboard"></i>'; }, 2000);
                            });
                        } catch (err) {
                            console.warn('复制失败:', err);
                        }
                    });
                }
            } else {
                msgSpan.innerHTML = `<span class="sv-toast-brief">${escapeHtml(message)}</span><button type="button" class="sv-toast-copy sv-toast-copy-inline" title="${escapeHtml(t('common.copy') || '复制')}"><i class="bi bi-clipboard"></i></button>`;
                const copyBtn = msgSpan.querySelector('.sv-toast-copy');
                if (copyBtn) {
                    copyBtn.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        try {
                            navigator.clipboard.writeText(message).then(() => {
                                copyBtn.innerHTML = '<i class="bi bi-check-lg"></i>';
                                setTimeout(() => { copyBtn.innerHTML = '<i class="bi bi-clipboard"></i>'; }, 2000);
                            });
                        } catch (err) {
                            console.warn('复制失败:', err);
                        }
                    });
                }
            }
        } else {
            msgSpan.textContent = message;
        }

        // 错误类型添加重试按钮，点击后关闭通知并触发页面刷新
        if (type === 'error') {
            const actionHint = t('error.action_retry') || '';
            if (actionHint) {
                const actionBtn = document.createElement('button');
                actionBtn.className = 'sv-toast-action';
                actionBtn.textContent = actionHint;
                actionBtn.addEventListener('click', () => {
                    el.classList.add('toast-out');
                    setTimeout(() => el.remove(), 300);
                    // 尝试刷新当前页面数据
                    const btnRefresh = document.getElementById('btnRefresh');
                    if (btnRefresh) btnRefresh.click();
                });
                msgSpan.appendChild(actionBtn);
            }
        }

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

        // 设置自动关闭定时器
        setTimeout(() => {
            el.classList.add('toast-out');
            setTimeout(() => el.remove(), 300);
        }, duration);
    }

    // ===== 确认模态框 =====
    /**
     * @function confirm
     * @description 显示确认对话框模态框
     * @param {string} title - 对话框标题
     * @param {string} message - 确认消息内容
     * @param {Function} onConfirm - 确认按钮点击回调函数
     * @returns {void}
     */
    function confirm(title, message, onConfirm) {
        const modal = document.getElementById('confirmModal');
        const titleEl = document.getElementById('confirmTitle');
        const msgEl = document.getElementById('confirmMessage');
        const actionBtn = document.getElementById('confirmAction');

        if (!modal || !titleEl || !msgEl || !actionBtn) return;

        titleEl.textContent = title;
        msgEl.textContent = message;

        // 终止之前的事件监听，避免重复绑定
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

    /**
     * @function trapFocus
     * @description 在模态框内设置焦点陷阱，确保Tab键不会跳出模态框（无障碍访问支持）
     * @param {HTMLElement} modalEl - 模态框元素
     * @returns {void}
     * @private
     */
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

    /**
     * @function releaseFocus
     * @description 释放模态框的焦点陷阱，移除键盘事件监听
     * @param {HTMLElement} modalEl - 模态框元素
     * @returns {void}
     * @private
     */
    function releaseFocus(modalEl) {
        if (modalEl._focusTrapHandler) {
            modalEl.removeEventListener('keydown', modalEl._focusTrapHandler);
            delete modalEl._focusTrapHandler;
        }
    }

    /**
     * @function openModal
     * @description 打开指定ID的模态框，保存之前的焦点元素，设置焦点陷阱
     * @param {string} id - 模态框元素ID
     * @returns {void}
     */
    function openModal(id) {
        const modal = document.getElementById(id);
        if (modal) {
            modal._previousFocus = document.activeElement;
            modal.classList.add('show');
            trapFocus(modal);
        }
    }

    /**
     * @function closeModal
     * @description 关闭指定ID的模态框，释放焦点陷阱，恢复焦点到之前的元素，带退出动画
     * @param {string} id - 模态框元素ID
     * @returns {void}
     */
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
    /**
     * @function setupUploadZone
     * @description 初始化文件上传区域，支持点击选择和拖拽上传
     * @param {HTMLElement} zone - 上传区域DOM元素
     * @param {HTMLInputElement} fileInput - 文件输入input元素
     * @param {Object} [callbacks] - 回调函数对象
     * @param {Function} [callbacks.onFileSelected] - 文件选择后的回调，参数为选中的File对象
     * @param {Function} [callbacks.onFileCleared] - 文件清除后的回调
     * @returns {void}
     */
    function setupUploadZone(zone, fileInput, callbacks = {}) {
        if (!zone || !fileInput) return;

        // 点击上传区域触发文件选择
        zone.addEventListener('click', (e) => {
            if (e.target !== fileInput) {
                fileInput.click();
            }
        });

        // 监听文件选择变化
        fileInput.addEventListener('change', () => {
            if (fileInput.files && fileInput.files[0]) {
                zone.classList.add('has-file');
                if (callbacks.onFileSelected) callbacks.onFileSelected(fileInput.files[0]);
            } else {
                zone.classList.remove('has-file');
                if (callbacks.onFileCleared) callbacks.onFileCleared();
            }
        });

        // 拖拽事件处理
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
                // 使用DataTransfer API设置文件到input元素
                const dt = new DataTransfer();
                dt.items.add(files[0]);
                fileInput.files = dt.files;

                zone.classList.add('has-file');
                if (callbacks.onFileSelected) callbacks.onFileSelected(files[0]);
            }
        });
    }

    // ===== 全局 SSE 连接 =====
    /**
     * @var {EventSource|null} globalEventSource
     * @description 全局SSE连接实例，用于接收服务器推送的系统状态事件
     * @private
     */
    let globalEventSource = null;
    /**
     * @var {number} _sseRetryCount
     * @description SSE连接重试计数器
     * @private
     */
    let _sseRetryCount = 0;
    /**
     * @var {number|null} _sseRetryTimer
     * @description SSE重设定时器ID
     * @private
     */
    let _sseRetryTimer = null;
    /**
     * @constant {number} SSE_MAX_RETRIES
     * @description SSE连接最大重试次数，超过后停止重连并通知用户
     * @default 10
     */
    const SSE_MAX_RETRIES = 10;

    /**
     * @function _updateSSEStatusUI
     * @description 更新SSE连接状态UI指示器（状态栏小圆点）
     * @param {string} state - 连接状态：online/reconnecting/offline
     * @returns {void}
     * @private
     */
    function _updateSSEStatusUI(state) {
        const dot = document.getElementById('statusDot');
        if (!dot) return;
        dot.classList.remove('online', 'reconnecting', 'offline');
        if (state === 'online') {
            dot.classList.add('online');
            dot.title = '';
        } else if (state === 'reconnecting') {
            dot.classList.add('reconnecting');
            dot.title = t('system.connection_failed');
        } else {
            dot.classList.add('offline');
            dot.title = t('system.connection_failed');
        }
    }

    /**
     * @function updateStatusFromEvent
     * @description 从SSE事件数据更新系统状态栏（GPU状态、模型加载状态）
     * @param {Object} data - SSE事件数据对象
     * @param {boolean} [data.gpu_available] - GPU是否可用
     * @param {string} [data.gpu_name] - GPU名称
     * @param {string} [data.status] - 模型状态：loaded/loading/unloading/unloaded/error
     * @returns {void}
     */
    function updateStatusFromEvent(data) {
        const statusModel = document.getElementById('statusModel');
        const statusGpu = document.getElementById('statusGpu');
        if (!statusModel || !statusGpu) return;

        // 更新GPU状态显示
        if (data.gpu_available !== undefined) {
            const gpuName = data.gpu_name || 'NVIDIA';
            if (data.gpu_available) {
                statusGpu.textContent = 'GPU: ' + gpuName;
                statusGpu.style.color = 'var(--sv-primary)';
            } else {
                statusGpu.textContent = 'GPU: 不可用';
                statusGpu.style.color = 'var(--sv-warning)';
            }
        }

        // 更新模型加载状态显示
        if (data.status === 'loaded') {
            statusModel.textContent = t('status.model_loaded') || '已加载';
            statusModel.style.color = 'var(--sv-primary)';
        } else if (data.status === 'loading') {
            statusModel.textContent = t('status.model_loading') || '加载中...';
            statusModel.style.color = 'var(--sv-accent-terracotta)';
        } else if (data.status === 'unloading' || data.status === 'unloaded') {
            statusModel.textContent = t('status.model_unloaded') || '未加载';
            statusModel.style.color = 'var(--sv-text-muted)';
        } else if (data.status === 'error') {
            statusModel.textContent = t('status.model_error') || '错误';
            statusModel.style.color = 'var(--sv-error)';
        }
    }

    /**
     * @function initGlobalSSE
     * @description 初始化全局SSE连接，支持自动重连（指数退避策略），监听心跳、进度、模型状态等事件
     * @returns {void}
     */
    function initGlobalSSE() {
        // 关闭现有连接
        if (globalEventSource) {
            globalEventSource.close();
            globalEventSource = null;
        }
        if (_sseRetryTimer) {
            clearTimeout(_sseRetryTimer);
            _sseRetryTimer = null;
        }

        // 超过最大重试次数，停止重连
        if (_sseRetryCount >= SSE_MAX_RETRIES) {
            console.error('SSE max retries reached, stopping reconnection');
            _updateSSEStatusUI('offline');
            toast(t('system.connection_failed') || 'Connection lost. Please refresh the page.', 'error', 8000);
            return;
        }

        globalEventSource = new EventSource('/api/sse/events');
        window.__sseConnection = globalEventSource;

        // 心跳事件处理（保持连接活跃）
        globalEventSource.addEventListener('heartbeat', (event) => {
            try {
                const data = JSON.parse(event.data);
                // 静默处理心跳，不打印日志
            } catch (err) {
                console.debug('SSE heartbeat parse error:', err);
            }
        });

        // 进度事件处理（由具体页面订阅处理，此处仅监听通道）
        globalEventSource.addEventListener('progress', (event) => {
            try {
                const data = JSON.parse(event.data);
                // 进度事件由具体页面处理，这里只做SSE通道监听
            } catch (err) {
                console.debug('SSE progress parse error:', err);
            }
        });

        // 模型状态事件处理
        globalEventSource.addEventListener('model_status', (event) => {
            try {
                const data = JSON.parse(event.data);
                // 更新系统状态栏
                updateStatusFromEvent(data);
            } catch (err) {
                console.debug('SSE model_status parse error:', err);
            }
        });

        // 连接成功时重置重试计数
        globalEventSource.onopen = () => {
            if (_sseRetryCount > 0) {
                console.debug('SSE reconnected after', _sseRetryCount, 'attempts');
                toast(t('system.reconnected') || 'Reconnected', 'success', 2000);
            }
            _sseRetryCount = 0;
            _updateSSEStatusUI('online');
        };

        // 连接错误时使用指数退避策略重连
        globalEventSource.onerror = () => {
            globalEventSource.close();
            globalEventSource = null;
            window.__sseConnection = null;
            _sseRetryCount++;
            _updateSSEStatusUI('reconnecting');
            // 指数退避：1s, 2s, 4s, 8s... 最大30s
            const delay = Math.min(1000 * Math.pow(2, _sseRetryCount - 1), 30000);
            console.debug('SSE connection error, retrying in', delay, 'ms (attempt', _sseRetryCount, ')');
            _sseRetryTimer = setTimeout(() => {
                initGlobalSSE();
            }, delay);
        };

        // 页面卸载前关闭连接
        window.addEventListener('beforeunload', () => {
            if (_sseRetryTimer) {
                clearTimeout(_sseRetryTimer);
                _sseRetryTimer = null;
            }
            if (globalEventSource) {
                globalEventSource.close();
                globalEventSource = null;
                window.__sseConnection = null;
            }
        });
    }

    // ===== SSE 统一修复进度 =====
    /**
     * @var {EventSource|null} currentRestoreEventSource
     * @description 当前修复任务的SSE进度连接实例
     * @private
     */
    let currentRestoreEventSource = null;
    /** @var {boolean} _restoreSessionCleared - 标记会话已被清除，防止 beforeunload 重新保存 */
    let _restoreSessionCleared = false;

    /**
     * @function startRestoreProgressSSE
     * @description 启动修复任务进度SSE监听，实时更新进度条、FPS、阶段、预估剩余时间等UI
     * @param {string} taskId - 修复任务ID
     * @param {string} taskType - 任务类型：'video' 或 'image'
     * @returns {void}
     */

    /**
     * @function saveRestoreSession
     * @description Save current restore page state snapshot to localStorage, called on page unload
     * and periodically during progress—so switching pages and coming back restores everything.
     * @param {Object} overrides - Fields to override in the saved snapshot
     * @returns {void}
     */
        // === saveRestoreSession (fire-and-forget) ===
        function saveRestoreSession(overrides) {
            try {
                // 会话已被 restoreRestoreSession 清除，不再重新保存
                if (_restoreSessionCleared && !overrides.taskId) return;
                overrides = overrides || {};
                var existing = {};
                try { existing = JSON.parse(localStorage.getItem('sv_restore_session') || '{}'); } catch(e) {}
                var snap = { savedAt: Date.now() };
                // Carry forward known safe keys
                var keys = ['taskId','taskType','status','beforeSrc','fileName','fileSize',
                            'progress','progress_stage','taskStatus',
                            'batchId','batchTotal','batchCompleted','batchFailed'];
                for (var i = 0; i < keys.length; i++) {
                    if (existing[keys[i]] !== undefined) snap[keys[i]] = existing[keys[i]];
                }
                // Merge overrides
                var ovKeys = Object.keys(overrides);
                for (var j = 0; j < ovKeys.length; j++) {
                    snap[ovKeys[j]] = overrides[ovKeys[j]];
                }
                // Safely capture file info from DOM
                try {
                    var fi = document.getElementById('restoreFileInfo');
                    if (fi && fi.style && fi.style.display !== 'none' && !snap.fileName) {
                        var n = fi.querySelector('.sv-fileinfo-name');
                        var s = fi.querySelector('.sv-fileinfo-size');
                        if (n) snap.fileName = n.textContent || '';
                        if (s) snap.fileSize = s.textContent || '';
                    }
                } catch(e) {}
                try {
                    var bc = document.getElementById('batchProgressCard');
                    if (bc && bc.style && bc.style.display !== 'none') {
                        snap.batchId = snap.batchId || existing.batchId;
                    }
                } catch(e) {}
                if (snap.fileName || snap.taskId || snap.batchId) {
                    localStorage.setItem('sv_restore_session', JSON.stringify(snap));
                }
            } catch(e) { /* Never let saveRestoreSession break the caller */ }
        }
    
        /**
         * @function restoreRestoreSession
     * @description On page load, check for a saved restore session and restore UI state.
     * Handles: completed (show result), processing (re-connect SSE), pending, failed.
     * @returns {Promise<void>}
     */
    async function restoreRestoreSession() {
        try {
            var saved = localStorage.getItem('sv_restore_session');
            if (!saved) return;
            var snap = JSON.parse(saved);
            // 所有含有 taskId 的会话一律清除——用户回到修复页面应看到干净的上传界面
            // 原因：服务器重启后旧任务已不活跃，SSE 也无法重连，恢复这些会话会导致空白
            if (snap.taskId) {
                localStorage.removeItem('sv_restore_session');
                _restoreSessionCleared = true;
                return;
            }
            // 无 taskId 的 uploaded 状态也清除
            localStorage.removeItem('sv_restore_session');
            _restoreSessionCleared = true;
        } catch(e) { /* ignore - best effort restore */ }
    }

    /** @var {number} _restoreSseRetryCount SSE重连计数 */
    let _restoreSseRetryCount = 0;
    /** @var {number} _restoreSseMaxRetries SSE最大重连次数 */
    const _restoreSseMaxRetries = 20;

    function startRestoreProgressSSE(taskId, taskType) {
        // 关闭之前的连接
        if (currentRestoreEventSource) {
            currentRestoreEventSource.close();
            currentRestoreEventSource = null;
        }

        // 设置当前任务ID供取消按钮使用
        if (typeof window !== 'undefined' && window.currentTaskId !== undefined) {
            window.currentTaskId = taskId;
        }

        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');
        const progressPct = document.getElementById('progressPct');
        const progressFrames = document.getElementById('progressFrames');
        const progressEta = document.getElementById('progressEta');
        const progressDetail = document.getElementById('progressDetail');
        const progressFps = document.getElementById('progressFps');
        const progressStage = document.getElementById('progressStage');
        const taskStatus = document.getElementById('taskStatus');

        const es = new EventSource(`/api/restore/${taskId}/progress`);
        currentRestoreEventSource = es;

        let startTime = Date.now();
        let lastFrame = 0;
        let lastFrameTime = Date.now();
        const _I = window.__I18N__ || {};
        const typeLabel = taskType === 'video' ? (_I['history.video'] || t('history.video')) : (_I['history.image'] || t('history.image'));

        // 标记任务是否已终结（completed/failed/cancelled），避免重连已结束的任务
        let taskFinished = false;
        // 进度卡死检测：记录进度为0%的持续时间
        let zeroProgressStart = Date.now();
        const ZERO_STUCK_THRESHOLD_MS = 60000; // 进度为0%超过60秒视为卡死
        // 非零进度卡死检测：进度值长时间不变化也视为卡死
        let lastProgressValue = 0;
        let lastProgressChangeTime = Date.now();
        const PROGRESS_STUCK_THRESHOLD_MS = 300000; // 进度不变超过5分钟视为卡死

        es.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // SSE error event: task doesn't exist or other server error
                if (data.error) {
                    console.warn('SSE error:', data.error);
                    taskFinished = true;
                    es.close();
                    currentRestoreEventSource = null;
                    _restoreSseRetryCount = 0;
                    if (typeof window !== 'undefined') window.currentTaskId = null;
                    // 清除会话并隐藏进度卡片
                    try { localStorage.removeItem('sv_restore_session'); } catch(e) {}
                    const pc = document.getElementById('progressCard');
                    if (pc) pc.style.display = 'none';
                    toast(data.error || '任务不存在', 'warning');
                    return;
                }

                // SSE 超时事件：服务端在 max_duration 后发送，任务可能仍在运行
                if (data.status === 'timeout') {
                    es.close();
                    currentRestoreEventSource = null;
                    if (!taskFinished) {
                        _restoreSseRetryCount++;
                        if (_restoreSseRetryCount <= _restoreSseMaxRetries) {
                            console.debug('SSE timeout, auto-reconnecting (' + _restoreSseRetryCount + '/' + _restoreSseMaxRetries + ')');
                            // 指数退避重连：2s, 4s, 8s... 最大 15s
                            const retryDelay = Math.min(2000 * Math.pow(2, _restoreSseRetryCount - 1), 15000);
                            setTimeout(() => {
                                // 仅在进度卡未关闭时重连（用户可能已手动取消或离开页面）
                                const pc = document.getElementById('progressCard');
                                if (pc && pc.style.display !== 'none') {
                                    startRestoreProgressSSE(taskId, taskType);
                                }
                            }, retryDelay);
                        } else {
                            toast(_I['system.connection_failed'] || t('system.connection_failed'), 'warning', 8000);
                        }
                    }
                    return;
                }

                // 重置重连计数（收到有效数据说明连接正常）
                _restoreSseRetryCount = 0;

                // 进度卡死检测：如果进度为0%超过阈值，视为任务卡死
                if (data.progress > 0) {
                    zeroProgressStart = Date.now(); // 有进度则重置计时
                    // 检测进度值是否发生变化
                    if (data.progress !== lastProgressValue) {
                        lastProgressValue = data.progress;
                        lastProgressChangeTime = Date.now();
                    } else if (data.status === 'processing' && (Date.now() - lastProgressChangeTime) > PROGRESS_STUCK_THRESHOLD_MS) {
                        // 进度值长时间不变（非零），也视为卡死
                        console.warn('Task appears stuck: progress unchanged at ' + data.progress + '% for ' + PROGRESS_STUCK_THRESHOLD_MS / 1000 + 's');
                        taskFinished = true;
                        es.close();
                        currentRestoreEventSource = null;
                        if (typeof window !== 'undefined') window.currentTaskId = null;
                        try { localStorage.removeItem('sv_restore_session'); } catch(e) {}
                        const pc = document.getElementById('progressCard');
                        if (pc) pc.style.display = 'none';
                        toast(_I['restore.task_stuck'] || '任务似乎已卡死，请重新开始', 'warning');
                        return;
                    }
                } else if (data.status === 'processing' && (Date.now() - zeroProgressStart) > ZERO_STUCK_THRESHOLD_MS) {
                    console.warn('Task appears stuck: 0% progress for ' + STUCK_THRESHOLD_MS / 1000 + 's');
                    taskFinished = true;
                    es.close();
                    currentRestoreEventSource = null;
                    if (typeof window !== 'undefined') window.currentTaskId = null;
                    try { localStorage.removeItem('sv_restore_session'); } catch(e) {}
                    const pc = document.getElementById('progressCard');
                    if (pc) pc.style.display = 'none';
                    toast(_I['restore.task_stuck'] || '任务似乎已卡死，请重新开始', 'warning');
                    return;
                }

                // 更新进度条（使用transform:scaleX提升性能，避免重排）
                if (progressBar) {
                    progressBar.style.transform = `scaleX(${data.progress / 100})`;
                    progressBar.setAttribute('aria-valuenow', Math.round(data.progress));
                    if (data.progress >= 100) {
                        progressBar.classList.remove('animated');
                        progressBar.classList.add('bg-success');
                    }
                }

                // 更新百分比文本
                if (progressPct) progressPct.textContent = `${Math.round(data.progress)}%`;
                if (progressFrames) {
                    if (taskType === 'video' && data.total_frames) {
                        progressFrames.textContent = `${data.current_frame} / ${data.total_frames} 帧`;
                    } else if (taskType === 'image' && data.message) {
                        progressFrames.textContent = data.message;
                    } else {
                        progressFrames.textContent = '';
                    }
                }

                // 基于已用时间和进度预估剩余时间
                if (progressEta) {
                    if (data.progress > 2 && data.progress < 99) {
                        const elapsed = (Date.now() - startTime) / 1000;
                        const eta = (elapsed / data.progress) * (100 - data.progress);
                        if (eta > 5) {
                            progressEta.textContent = `约 ${formatDuration(eta)}`;
                        } else {
                            progressEta.textContent = '即将完成';
                        }
                    } else {
                        progressEta.textContent = '';
                    }
                }

                // 视频任务显示详细信息：FPS和处理阶段
                if (progressDetail && taskType === 'video' && data.current_frame) {
                    progressDetail.style.display = '';
                    // FPS计算：统计帧间隔时间
                    const now = Date.now();
                    const framesDelta = (data.current_frame || 0) - lastFrame;
                    const timeDelta = (now - lastFrameTime) / 1000;
                    if (framesDelta > 0 && timeDelta > 0.5) {
                        const fps = (framesDelta / timeDelta).toFixed(1);
                        if (progressFps) progressFps.textContent = `${fps} fps`;
                        lastFrame = data.current_frame;
                        lastFrameTime = now;
                    }
                    // 根据进度判断处理阶段
                    if (progressStage) {
                        const progress = data.progress || 0;
                        if (progress < 10) progressStage.textContent = _I['restore.stage_encoding'] || 'Encoding';
                        else if (progress < 85) progressStage.textContent = _I['restore.stage_denoising'] || 'Denoising';
                        else progressStage.textContent = _I['restore.stage_decoding'] || 'Decoding';
                    }
                }

                // 图片任务：显示阶段信息（来自服务端的 message 字段）
                if (progressDetail && taskType === 'image' && data.message) {
                    progressDetail.style.display = '';
                    if (progressStage) progressStage.textContent = data.message;
                }

                // 更新状态文本
                if (progressText) {
                    const statusTexts = {
                        pending: _I['status.pending'] || t('status.pending'),
                        processing: `${_I['restore.processing'] || t('restore.processing')} (${data.progress}%)`,
                    };
                    progressText.textContent = statusTexts[data.status] || (_I['restore.processing'] || t('restore.processing'));
                }

                // 每次收到进度数据时更新持久化快照
                try {
                    const ps = JSON.parse(localStorage.getItem('sv_restore_session') || '{}');
                    ps.progress = data.progress;
                    ps.progress_stage = data.stage || ps.progress_stage;
                    ps.progress_fps = data.fps || ps.progress_fps;
                    ps.progress_text = data.message || ps.progress_text;
                    ps.eta = data.eta || ps.eta;
                    if (data.status) ps.taskStatus = data.status;
                    localStorage.setItem('sv_restore_session', JSON.stringify(ps));
                } catch (e) {}

                if (data.status === 'completed') {
                    taskFinished = true;
                    es.close();
                    currentRestoreEventSource = null;
                    _restoreSseRetryCount = 0;
                    if (typeof window !== 'undefined') window.currentTaskId = null;
                    if (progressText) progressText.textContent = _I['restore.completed'] || t('restore.completed');
                    if (progressEta) progressEta.textContent = '';
                    if (progressDetail) progressDetail.style.display = 'none';
                    if (progressFrames) progressFrames.textContent = '';
                    if (taskStatus) {
                        taskStatus.textContent = _I['status.completed'] || t('status.completed');
                        taskStatus.className = 'sv-badge sv-badge-completed';
                    }

                    // 显示结果区域（附带耗时等元信息）
                    var _rMeta = { elapsedSec: (Date.now() - startTime) / 1000 };
                    if (data.processing_time && data.processing_time > 0) { _rMeta.processingTime = Number(data.processing_time); }
                    showRestoreResult(taskId, taskType || data.task_type, _rMeta);
                    toast(`${typeLabel}: ${_I['restore.completed'] || t('restore.completed')}`, 'success');
                }

                // 任务失败处理
                if (data.status === 'failed') {
                    taskFinished = true;
                    es.close();
                    currentRestoreEventSource = null;
                    _restoreSseRetryCount = 0;
                    if (typeof window !== 'undefined') window.currentTaskId = null;
                    if (progressText) progressText.textContent = _I['restore.failed'] || t('restore.failed');
                    if (progressDetail) progressDetail.style.display = 'none';
                    if (taskStatus) {
                        taskStatus.textContent = _I['status.failed'] || t('status.failed');
                        taskStatus.className = 'sv-badge sv-badge-failed';
                    }
                    showRestoreError(data.error || data.message || (_I['restore.failed'] || t('restore.failed')));
                    return;
                }

                // 任务取消处理
                if (data.status === 'cancelled') {
                    taskFinished = true;
                    es.close();
                    currentRestoreEventSource = null;
                    _restoreSseRetryCount = 0;
                    if (typeof window !== 'undefined') window.currentTaskId = null;
                    if (progressText) progressText.textContent = (window.__I18N__ && window.__I18N__['restore.cancel_task']) || 'Cancelled';
                    if (progressDetail) progressDetail.style.display = 'none';
                    if (taskStatus) {
                        taskStatus.textContent = (window.__I18N__ && window.__I18N__['status.cancelled']) || 'Cancelled';
                        taskStatus.className = 'sv-badge sv-badge-failed';
                    }
                }
            } catch (err) {
                console.error('SSE data parse error:', err);
            }
        };

        es.onerror = () => {
            es.close();
            currentRestoreEventSource = null;
            // 连接断开时自动重连（只要任务未终结）
            if (!taskFinished) {
                _restoreSseRetryCount++;
                // 连续失败3次以上，可能是任务不存在，清除会话
                if (_restoreSseRetryCount > 3) {
                    console.warn('SSE connection failed ' + _restoreSseRetryCount + ' times, task may not exist');
                    taskFinished = true;
                    _restoreSseRetryCount = 0;
                    if (typeof window !== 'undefined') window.currentTaskId = null;
                    try { localStorage.removeItem('sv_restore_session'); } catch(e) {}
                    const pc = document.getElementById('progressCard');
                    if (pc) pc.style.display = 'none';
                    toast(_I['restore.task_not_found'] || '任务已不存在或已过期', 'warning');
                    return;
                }
                if (_restoreSseRetryCount <= _restoreSseMaxRetries) {
                    console.debug('SSE connection lost, auto-reconnecting (' + _restoreSseRetryCount + '/' + _restoreSseMaxRetries + ')');
                    const retryDelay = Math.min(2000 * Math.pow(2, _restoreSseRetryCount - 1), 15000);
                    setTimeout(() => {
                        const pc = document.getElementById('progressCard');
                        if (pc && pc.style.display !== 'none') {
                            startRestoreProgressSSE(taskId, taskType);
                        }
                    }, retryDelay);
                } else {
                    toast(_I['system.connection_failed'] || t('system.connection_failed'), 'warning', 8000);
                }
            }
        };
    }

    /**
     * @function showRestoreResult
     * @description 修复完成后显示结果区域，视频显示播放器，图片显示前后对比滑块
     * @param {string} taskId - 修复任务ID
     * @param {string} taskType - 任务类型：'video' 或 'image'
     * @returns {void}
     * @private
     */
    function showRestoreResult(taskId, taskType, meta) {
        meta = meta || {};
        const progressCard = document.getElementById('progressCard');
        const resultCard = document.getElementById('resultCard');
        const resultVideo = document.getElementById('resultVideo');
        const btnDownload = document.getElementById('btnDownload');

        const errorCard = document.getElementById('errorCard');
        if (errorCard) errorCard.style.display = 'none';

        if (progressCard) progressCard.style.display = 'none';
        if (resultCard) resultCard.style.display = 'block';
        if (btnDownload) {
            btnDownload.href = `/api/restore/${taskId}/download`;
            btnDownload.removeAttribute('disabled');
        }

        // 结果 meta 信息（耗时等）- 优先使用后端真实 processing_time 保证与终端日志一致，前端计时兜底
        const resultMetaText = document.getElementById('resultMetaText');
        if (resultMetaText) {
            let elapsedSec = null;
            if (meta.processingTime != null && isFinite(meta.processingTime)) elapsedSec = meta.processingTime;
            else if (meta.elapsedSec != null && isFinite(meta.elapsedSec)) elapsedSec = meta.elapsedSec;
            if (elapsedSec != null && isFinite(elapsedSec) && elapsedSec > 0) {
                resultMetaText.textContent = `耗时 ${formatDuration(elapsedSec)}`;
                resultMetaText.style.display = '';
            } else {
                resultMetaText.style.display = 'none';
            }
        }

        // 画布工具条：结果显示后按任务类型启用对应操作组
        const canvasStateLabel = document.getElementById('canvasStateLabel');
        if (canvasStateLabel) canvasStateLabel.textContent = t('status.completed');
        const setBtn = (id, enabled) => {
            const b = document.getElementById(id);
            if (b) { enabled ? b.removeAttribute('disabled') : b.setAttribute('disabled', ''); }
        };
        setBtn('btnRestoreAgain', true);
        setBtn('btnCanvasClear', true);
        setBtn('btnCanvasReplace', true);
        const tbFileName = document.getElementById('tbFileName');
        if (tbFileName) tbFileName.style.display = '';

        const compareCard = document.getElementById('compareCard');
        const plainViewer = document.getElementById('plainViewer');

        // 持久化结果状态到 sessionStorage，切页返回时可恢复
        const beforeSrc = document.getElementById('imagePreview')?.src || '';
        try {
            sessionStorage.setItem('sv_restore_result', JSON.stringify({
                taskId, taskType, beforeSrc
            }));
        } catch (e) { /* ignore quota errors */ }

        if (taskType === 'video') {
            // 视频任务：启用「前后对比」查看器（video-compare.js），比对失败时回退单视频查看器
            const videoSrc = `/api/restore/${taskId}/download`;
            const videoCompareCard = document.getElementById('videoCompareCard');
            const videoPlainViewer = document.getElementById('videoPlainViewer');
            const beforeV = document.getElementById('videoCompareBefore');
            const afterV = document.getElementById('videoCompareAfterImg');

            // 隐藏图片对比/单图视图，默认进入视频对比
            if (compareCard) compareCard.style.display = 'none';
            if (plainViewer) plainViewer.style.display = 'none';
            if (videoCompareCard) videoCompareCard.style.display = 'block';
            if (videoPlainViewer) videoPlainViewer.style.display = 'none';

            // 启用对比/缩放工具按钮（视频不支持放大镜）
            setBtn('btnCanvasCompare', true);
            setBtn('btnMagnifier', false);
            ['btnCompareHorizontal', 'btnCompareVertical', 'btnCompareZoomIn', 'btnCompareZoomOut', 'btnCompareFit', 'btnCompareReset'].forEach(id => setBtn(id, true));
            const vidCmpToggle = document.getElementById('btnCanvasCompare');
            if (vidCmpToggle) vidCmpToggle.classList.add('active');

            // 填充 before/after 视频源（同源修复输出，展示修复前自动播放由控件控制）
            [beforeV, afterV].forEach((el) => {
                if (el) { el.src = videoSrc; el.muted = true; el.loop = true; el.playsInline = true; }
            });
            if (resultVideo) { resultVideo.src = videoSrc; }

            // 初始化视频对比滑块（video-compare.js 提供）
            if (typeof window.initVideoCompareSlider === 'function') {
                try { window.initVideoCompareSlider(taskId, videoSrc); } catch (e) { console.error('视频对比初始化失败:', e); }
            }

            // 若 before 视频无法解码 → 回退到单视频查看器并给出提示
            if (beforeV) {
                beforeV.onerror = function () {
                    if (videoCompareCard) videoCompareCard.style.display = 'none';
                    if (videoPlainViewer) videoPlainViewer.style.display = 'flex';
                    if (resultVideo) resultVideo.style.display = 'block';
                    setBtn('btnCanvasCompare', false);
                    ['btnCompareHorizontal', 'btnCompareVertical', 'btnCompareZoomIn', 'btnCompareZoomOut', 'btnCompareFit', 'btnCompareReset'].forEach(id => setBtn(id, false));
                    console.warn('视频对比加载失败，已回退单查看模式（可能视频编码不受浏览器支持）');
                };
            }
            return;
        }

        // 图片任务：默认进入前后对比查看器
        const afterSrc = `/api/restore/${taskId}/download`;
        if (compareCard) compareCard.style.display = 'block';
        if (plainViewer) plainViewer.style.display = 'none';
        setBtn('btnCanvasCompare', true);
        setBtn('btnMagnifier', true);
        const cmpToggle = document.getElementById('btnCanvasCompare');
        if (cmpToggle) cmpToggle.classList.add('active');
        ['btnCompareHorizontal', 'btnCompareVertical', 'btnCompareZoomIn', 'btnCompareZoomOut', 'btnCompareFit', 'btnCompareReset']
            .forEach(id => setBtn(id, true));
        const compareBefore = document.getElementById('compareBefore');
        const compareAfterImg = document.getElementById('compareAfterImg');
        const plainImg = document.getElementById('plainImg');
        if (compareBefore) compareBefore.src = beforeSrc;
        if (compareAfterImg) compareAfterImg.src = afterSrc;
        if (plainImg) plainImg.src = afterSrc;
        initCompareSlider('compareContainer', 'compareSlider', 'compareAfter');

        // 记住查看偏好：对比方向 / 放大镜 / 对比模式
        const vp = loadViewPrefs();
        if (activeCompareSlider) {
            if (vp.dir === 'horizontal' || vp.dir === 'vertical') activeCompareSlider.setMode(vp.dir);
            if (vp.magnifier) {
                activeCompareSlider.setMagnifier(true);
                const mb = document.getElementById('btnMagnifier');
                if (mb) mb.classList.add('active');
            }
        }
        if (vp.compare === false && compareCard && plainViewer) {
            compareCard.style.display = 'none';
            plainViewer.style.display = 'flex';
            if (cmpToggle) cmpToggle.classList.remove('active');
        }
    }

    /**
     * @function showRestoreError
     * @description 修复失败：显示错误卡片 + 重试入口，工具条回到仅保留清除/替换
     * @param {string} msg - 错误信息
     * @returns {void}
     * @private
     */
    function showRestoreError(msg) {
        const progressCard = document.getElementById('progressCard');
        const resultCard = document.getElementById('resultCard');
        const errorCard = document.getElementById('errorCard');
        const errorMsg = document.getElementById('errorMsg');
        const compareCard = document.getElementById('compareCard');
        const plainViewer = document.getElementById('plainViewer');
        const resultVideo = document.getElementById('resultVideo');

        if (progressCard) progressCard.style.display = 'none';
        if (resultCard) resultCard.style.display = 'block';
        if (compareCard) compareCard.style.display = 'none';
        if (plainViewer) plainViewer.style.display = 'none';
        const videoCc = document.getElementById('videoCompareCard');
        const videoPv = document.getElementById('videoPlainViewer');
        if (videoCc) videoCc.style.display = 'none';
        if (videoPv) videoPv.style.display = 'none';
        if (resultVideo) { resultVideo.style.display = 'none'; resultVideo.src = ''; }
        if (errorMsg) errorMsg.textContent = msg || (window.__I18N__ && window.__I18N__['restore.failed']) || '修复失败，请重试';
        if (errorCard) errorCard.style.display = 'flex';

        const canvasStateLabel = document.getElementById('canvasStateLabel');
        if (canvasStateLabel) canvasStateLabel.textContent = (window.__I18N__ && window.__I18N__['status.failed']) || t('status.failed');
        const setBtn = (id, enabled) => { const b = document.getElementById(id); if (b) { enabled ? b.removeAttribute('disabled') : b.setAttribute('disabled', ''); } };
        setBtn('btnCanvasClear', true);
        setBtn('btnCanvasReplace', true);
        setBtn('btnDownload', false);
        setBtn('btnRestoreAgain', false);
        setBtn('btnCanvasCompare', false);
        setBtn('btnMagnifier', false);
        ['btnCompareHorizontal', 'btnCompareVertical', 'btnCompareZoomIn', 'btnCompareZoomOut', 'btnCompareFit', 'btnCompareReset']
            .forEach(id => setBtn(id, false));
        const resultMetaText = document.getElementById('resultMetaText');
        if (resultMetaText) { resultMetaText.style.display = 'none'; resultMetaText.textContent = ''; }

        // 重试：复用页面级 startRestore（由 restore.html 内联注入）
        const btnRetry = document.getElementById('btnRetry');
        if (btnRetry) {
            btnRetry.onclick = () => {
                if (typeof window.__retryRestore === 'function') {
                    if (errorCard) errorCard.style.display = 'none';
                    window.__retryRestore();
                }
            };
        }
    }

    /**
     * @function cancelRestoreTask
     * @description 取消正在进行的修复任务
     * @param {string} taskId - 要取消的修复任务ID
     * @returns {Promise<void>}
     */
    async function cancelRestoreTask(taskId) {
        try {
            await api.post(`/api/restore/${taskId}/cancel`, {});
            toast(t('task.canceled'), 'info');
        } catch (err) {
            toast((t('task.cancel_failed') + ': ' + err.message), 'error');
        }
    }

    // ===== 放大镜 / 预览查看器 / 对比滑块 =====
    let activeCompareSlider = null;
    let activePreviewViewer = null;

    /**
     * @function setLoupeLayer
     * @description 设置放大镜单个图层：按「主视图当前倍率 × 2」渲染局部放大背景
     */
    function setLoupeLayer(layer, imgUrl, natW, natH, dispScale, nx, ny, lensW, lensH) {
        if (!layer || !imgUrl) return;
        layer.style.backgroundImage = `url("${imgUrl}")`;
        layer.style.backgroundSize = `${natW * dispScale}px ${natH * dispScale}px`;
        layer.style.backgroundPosition = `${lensW / 2 - nx * dispScale}px ${lensH / 2 - ny * dispScale}px`;
    }

    /**
     * @function initPreviewViewer
     * @description 初始化上传后图片预览查看器（缩放/拖动/双击适配/放大镜），图片类任务每次载入时调用
     * @param {string} stageId - 预览舞台容器ID
     * @param {string} wrapId - 图片包裹层ID（transform 作用在它上面）
     * @param {string} imgId - 预览图片ID
     * @returns {object} PreviewViewer 实例
     */
    function initPreviewViewer(stageId, wrapId, imgId) {
        destroyPreviewViewer();
        activePreviewViewer = new PreviewViewer(stageId, wrapId, imgId);
        return activePreviewViewer;
    }

    function destroyPreviewViewer() {
        if (activePreviewViewer) {
            try { activePreviewViewer.destroy(); } catch (e) { /* ignore */ }
            activePreviewViewer = null;
        }
    }

    function getActiveCompareSlider() { return activeCompareSlider; }
    function getActivePreviewViewer() { return activePreviewViewer; }

    /**
     * @function loadViewPrefs
     * @description 读取查看偏好（对比方向 / 放大镜 / 对比模式）
     */
    function loadViewPrefs() {
        try { return JSON.parse(localStorage.getItem('sv_view_prefs') || '{}'); } catch (e) { return {}; }
    }
    /**
     * @function saveViewPrefs
     * @description 合并保存查看偏好
     */
    function saveViewPrefs(patch) {
        try {
            const cur = loadViewPrefs();
            Object.keys(patch).forEach((k) => { cur[k] = patch[k]; });
            localStorage.setItem('sv_view_prefs', JSON.stringify(cur));
        } catch (e) { /* ignore */ }
    }

    /**
     * @class PreviewViewer
     * @description 上传后图片预览查看器：滚轮以光标为中心缩放、左/右键拖动平移、
     *              双击 适配/1:1、HUD 显示真实倍率、可选放大镜局部放大
     */
    class PreviewViewer {
        constructor(stageId, wrapId, imgId) {
            this.stage = document.getElementById(stageId);
            this.wrap = document.getElementById(wrapId);
            this.img = document.getElementById(imgId);
            if (!this.stage || !this.wrap || !this.img) return;

            this.mag = 1;            // 1 = 适配窗口
            this.fitMag = 1;
            this.oneToOneMag = 4;
            this.tx = 0; this.ty = 0;
            this.natW = 0; this.natH = 0;
            this.dragging = false;
            this.dragAbort = null;
            this.rafId = null;
            this.magnifierOn = false;
            this.loupe = document.getElementById('previewMagnifier');
            this.mgBefore = this.loupe ? this.loupe.querySelector('.mg-before') : null;
            this.mgAfter = this.loupe ? this.loupe.querySelector('.mg-after') : null;
            this._resizeCleanup = null;

            this._bindWheel();
            this._bindDrag();
            this._bindDblClick();
            this._bindMagnifier();
            this._bindResize();
            this._align();
        }

        _align() {
            const img = this.img;
            if (!img.complete || img.naturalWidth <= 0) {
                img.addEventListener('load', () => this._align(), { once: true });
                return;
            }
            this.natW = img.naturalWidth;
            this.natH = img.naturalHeight;
            const ratio = this.natW / this.natH;
            const rect = this.stage.getBoundingClientRect();
            const maxW = Math.max(200, rect.width - 16);
            const maxH = Math.max(200, rect.height - 16);
            let w = maxW, h = w / ratio;
            if (h > maxH) { h = maxH; w = h * ratio; }
            this.wrap.style.width = `${w}px`;
            this.wrap.style.height = `${h}px`;
            this.fitMag = 1;
            this.oneToOneMag = Math.max(1, this.natW / w);
            this._fit();
        }

        _applyTransform() {
            const cw = this.wrap.offsetWidth, ch = this.wrap.offsetHeight;
            const vpW = this.stage.clientWidth, vpH = this.stage.clientHeight;
            const baseL = this.wrap.offsetLeft, baseT = this.wrap.offsetTop;
            const contentW = cw * this.mag, contentH = ch * this.mag;
            if (contentW <= vpW) this.tx = (vpW - contentW) / 2 - baseL;
            else this.tx = Math.min(0, Math.max(vpW - contentW - baseL, this.tx));
            if (contentH <= vpH) this.ty = (vpH - contentH) / 2 - baseT;
            else this.ty = Math.min(0, Math.max(vpH - contentH - baseT, this.ty));
            this.wrap.style.transform = `translate(${this.tx}px, ${this.ty}px) scale(${this.mag})`;
            const pct = Math.round(this.mag / this.oneToOneMag * 100);
            const hud = document.getElementById('previewHud');
            if (hud) hud.textContent = pct + '%';
        }

        _fit() { this.mag = this.fitMag; this.tx = 0; this.ty = 0; this._applyTransform(); }
        _oneToOne() { this.mag = this.oneToOneMag; this._applyTransform(); }

        _setMag(m, cx, cy) {
            const r = this.stage.getBoundingClientRect();
            if (cx === undefined) { cx = r.width / 2; cy = r.height / 2; }
            const oldS = this.mag;
            const px = (cx - this.tx) / oldS, py = (cy - this.ty) / oldS;
            this.mag = Math.min(8, Math.max(Math.min(this.fitMag * 0.4, 0.5), m));
            this.tx = cx - px * this.mag;
            this.ty = cy - py * this.mag;
            this._applyTransform();
        }

        _bindWheel() {
            this.stage.addEventListener('wheel', (e) => {
                e.preventDefault();
                const r = this.stage.getBoundingClientRect();
                this._setMag(this.mag * (e.deltaY < 0 ? 1.18 : 1 / 1.18), e.clientX - r.left, e.clientY - r.top);
            }, { passive: false });
        }

        _bindDrag() {
            const onStart = (clientX, clientY) => {
                this.dragging = true;
                this.stage.classList.add('grabbing');
                if (this.dragAbort) this.dragAbort.abort();
                this.dragAbort = new AbortController();
                const sig = this.dragAbort.signal;
                const sx = this.tx, sy = this.ty;
                const onMove = (e) => {
                    if (!this.dragging) return;
                    e.preventDefault();
                    const cx = e.touches ? e.touches[0].clientX : e.clientX;
                    const cy = e.touches ? e.touches[0].clientY : e.clientY;
                    if (!this.rafId) {
                        this.rafId = requestAnimationFrame(() => {
                            this.tx = sx + (cx - clientX);
                            this.ty = sy + (cy - clientY);
                            this._applyTransform();
                            this.rafId = null;
                        });
                    }
                };
                const onEnd = () => {
                    this.dragging = false;
                    this.stage.classList.remove('grabbing');
                    if (this.dragAbort) { this.dragAbort.abort(); this.dragAbort = null; }
                    if (this.rafId) { cancelAnimationFrame(this.rafId); this.rafId = null; }
                };
                document.addEventListener('mousemove', onMove, { signal: sig });
                document.addEventListener('mouseup', onEnd, { signal: sig });
                document.addEventListener('touchmove', onMove, { signal: sig, passive: false });
                document.addEventListener('touchend', onEnd, { signal: sig });
            };

            // 仅左键平移（预览无分割线；右键交给浏览器/手势，避免冲突）
            this.stage.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return;
                e.preventDefault();
                onStart(e.clientX, e.clientY);
            });
            this.stage.addEventListener('touchstart', (e) => {
                if (e.touches.length === 1) onStart(e.touches[0].clientX, e.touches[0].clientY);
            }, { passive: true });
        }

        _bindDblClick() {
            this.stage.addEventListener('dblclick', () => {
                if (this.mag > this.fitMag * 1.02) this._fit();
                else this._oneToOne();
            });
        }

        _bindMagnifier() {
            this.stage.addEventListener('mousemove', (e) => this._updateMagnifier(e));
            this.stage.addEventListener('mouseleave', () => { if (this.loupe) this.loupe.hidden = true; });
        }

        _updateMagnifier(e) {
            if (!this.magnifierOn || !this.loupe) return;
            const r = this.stage.getBoundingClientRect();
            const mx = e.clientX - r.left, my = e.clientY - r.top;
            const lensW = this.loupe.clientWidth || 190, lensH = this.loupe.clientHeight || 190;
            const imgX = (mx - this.tx) / this.mag;
            const imgY = (my - this.ty) / this.mag;
            const w = this.wrap.offsetWidth, h = this.wrap.offsetHeight;
            const nx = imgX / w * this.natW, ny = imgY / h * this.natH;
            const dispScale = (this.mag / this.oneToOneMag) * 2;
            if (this.mgBefore) setLoupeLayer(this.mgBefore, this.img.src, this.natW, this.natH, dispScale, nx, ny, lensW, lensH);
            this.loupe.style.left = `${mx - lensW / 2}px`;
            this.loupe.style.top = `${my - lensH / 2}px`;
            this.loupe.hidden = false;
        }

        setMagnifier(on) {
            this.magnifierOn = !!on;
            if (this.loupe) this.loupe.hidden = !on;
            saveViewPrefs({ magnifier: !!on });
        }

        _bindResize() {
            if (this._resizeCleanup) return;
            let raf = 0;
            const onResize = () => {
                cancelAnimationFrame(raf);
                raf = requestAnimationFrame(() => this._align());
            };
            window.addEventListener('resize', onResize);
            let ro = null;
            if (typeof ResizeObserver !== 'undefined') {
                ro = new ResizeObserver(onResize);
                ro.observe(this.stage);
            }
            this._resizeCleanup = () => {
                cancelAnimationFrame(raf);
                window.removeEventListener('resize', onResize);
                if (ro) ro.disconnect();
            };
        }

        destroy() {
            if (this.dragAbort) this.dragAbort.abort();
            if (this.rafId) cancelAnimationFrame(this.rafId);
            if (this._resizeCleanup) { this._resizeCleanup(); this._resizeCleanup = null; }
            this.setMagnifier(false);
        }
    }

    /**
     * @function initCompareSlider
     * @description 初始化图片前后对比滑块，支持水平/垂直模式、缩放、平移、放大镜、键盘操作
     * @param {string} containerId - 对比容器元素ID
     * @param {string} sliderId - 滑块元素ID
     * @param {string} afterId - 修复后图片容器元素ID
     * @returns {object} CompareSlider 实例
     */
    function initCompareSlider(containerId, sliderId, afterId) {
        activeCompareSlider = new CompareSlider(containerId, sliderId, afterId);
        return activeCompareSlider;
    }

    /**
     * @class CompareSlider
     * @description 前后对比滑块控制器，支持水平/垂直模式、鼠标滚轮缩放、
     *              触摸 pinch-to-zoom、键盘方向键、双击重置、50% 吸附
     */
    class CompareSlider {
        constructor(containerId, sliderId, afterId) {
            this.container = document.getElementById(containerId);
            this.slider = document.getElementById(sliderId);
            this.afterEl = document.getElementById(afterId);
            if (!this.container || !this.slider || !this.afterEl) return;

            this.viewport = this.container.parentElement;
            this.mode = 'horizontal';   // 'horizontal' | 'vertical'
            this.position = 0.5;        // 0-1 归一化分割线位置
            this.fitMag = 1;            // 适配窗口 = 1（容器尺寸即适配尺寸）
            this.mag = 1;               // 当前放大倍率（1 = 适配窗口）
            this.oneToOneMag = 4;       // 1:1 原像素所需倍率（对齐后计算）
            this.tx = 0; this.ty = 0;   // 平移（屏幕像素，相对 viewport）
            this.isDragging = false;
            this.dragMode = null;       // 'div' 分割线 | 'pan' 平移
            this.dragAbort = null;
            this.snapThreshold = 0.03;
            this.rafId = null;
            this._alignCleanup = null;
            this.magnifierOn = false;
            this.natW = 0; this.natH = 0;
            this.beforeSrc = ''; this.afterSrc = '';
            this.loupe = document.getElementById('compareMagnifier');
            this.mgBefore = this.loupe ? this.loupe.querySelector('.mg-before') : null;
            this.mgAfter = this.loupe ? this.loupe.querySelector('.mg-after') : null;

            this._initState();
            this._bindDrag();
            this._bindZoom();
            this._bindKeyboard();
            this._bindDoubleClick();
            this._bindToolbar();
            this._bindMagnifier();
            this._bindImageLoad();
        }

        _initState() {
            this.container.classList.remove('vertical');
            this.afterEl.style.clipPath = 'inset(0 0 0 50%)';
            this._updateSliderUI(0.5);
        }

        // ── 视图变换（平移 + 缩放，transform-origin 0 0） ──

        _applyTransform() {
            const cw = this.container.offsetWidth, ch = this.container.offsetHeight;
            const vpW = this.viewport.clientWidth, vpH = this.viewport.clientHeight;
            const baseL = this.container.offsetLeft, baseT = this.container.offsetTop;
            const contentW = cw * this.mag, contentH = ch * this.mag;
            if (contentW <= vpW) this.tx = (vpW - contentW) / 2 - baseL;
            else this.tx = Math.min(0, Math.max(vpW - contentW - baseL, this.tx));
            if (contentH <= vpH) this.ty = (vpH - contentH) / 2 - baseT;
            else this.ty = Math.min(0, Math.max(vpH - contentH - baseT, this.ty));
            this.container.style.transform = `translate(${this.tx}px, ${this.ty}px) scale(${this.mag})`;
            this._syncLabel();
        }

        _syncLabel() {
            const pct = Math.round(this.mag / this.oneToOneMag * 100);
            const label = document.getElementById('compareZoomLabel');
            if (label) label.textContent = pct + '%';
            const hud = document.getElementById('compareHud');
            if (hud) hud.textContent = pct + '%';
        }

        _fit() {
            this.mag = this.fitMag;
            this.tx = 0; this.ty = 0;
            this._applyTransform();
        }

        _oneToOne() {
            this.mag = this.oneToOneMag;
            this._applyTransform();
        }

        _applyMag(newMag, cx, cy) {
            const vp = this.viewport.getBoundingClientRect();
            const oldS = this.mag;
            if (cx === undefined) { cx = vp.left + vp.width / 2; cy = vp.top + vp.height / 2; }
            // 保持光标下的图像点不动（以光标为中心缩放）
            const px = (cx - vp.left - this.container.offsetLeft - this.tx) / oldS;
            const py = (cy - vp.top - this.container.offsetTop - this.ty) / oldS;
            this.mag = Math.min(8, Math.max(Math.min(this.fitMag * 0.4, 0.5), newMag));
            this.tx = (cx - vp.left) - px * this.mag - this.container.offsetLeft;
            this.ty = (cy - vp.top) - py * this.mag - this.container.offsetTop;
            this._applyTransform();
        }

        _resetView() {
            this._fit();
            this._updateSliderUI(0.5);
        }

        // ── 滑块位置 ──

        _updateSliderUI(pos) {
            this.position = Math.max(0, Math.min(1, pos));
            if (this.mode === 'horizontal') {
                const w = this.container.offsetWidth;
                this.slider.style.transform = `translateX(${this.position * w}px)`;
                this.afterEl.style.clipPath = `inset(0 0 0 ${this.position * 100}%)`;
            } else {
                const h = this.container.offsetHeight;
                this.slider.style.transform = `translateY(${this.position * h}px)`;
                this.afterEl.style.clipPath = `inset(0 0 ${this.position * 100}% 0)`;
            }
        }

        _setPositionFromEvent(clientX, clientY) {
            const rect = this.container.getBoundingClientRect();
            let pos;
            if (this.mode === 'horizontal') {
                pos = (clientX - rect.left) / Math.max(1, rect.width);
            } else {
                pos = (clientY - rect.top) / Math.max(1, rect.height);
            }
            if (Math.abs(pos - 0.5) < this.snapThreshold) pos = 0.5;
            this._updateSliderUI(pos);
        }

        // ── 拖拽：分割线拖动 / 放大后平移 ──

        _bindDrag() {
            const onStart = (clientX, clientY, mode) => {
                this.isDragging = true;
                this.dragMode = mode;
                this.container.classList.add('no-transition');
                this.slider.classList.remove('snapping');
                this.slider.classList.add('is-dragging');
                if (mode === 'pan') this.container.classList.add('panning');
                if (this.dragAbort) this.dragAbort.abort();
                this.dragAbort = new AbortController();
                const sig = this.dragAbort.signal;
                const startTx = this.tx, startTy = this.ty;

                const onMove = (e) => {
                    if (!this.isDragging) return;
                    e.preventDefault();
                    const cx = e.touches ? e.touches[0].clientX : e.clientX;
                    const cy = e.touches ? e.touches[0].clientY : e.clientY;
                    if (!this.rafId) {
                        this.rafId = requestAnimationFrame(() => {
                            if (this.dragMode === 'div') this._setPositionFromEvent(cx, cy);
                            else {
                                this.tx = startTx + (cx - clientX);
                                this.ty = startTy + (cy - clientY);
                                this._applyTransform();
                            }
                            this.rafId = null;
                        });
                    }
                };

                const onEnd = () => {
                    this.isDragging = false;
                    this.dragMode = null;
                    this.container.classList.remove('no-transition');
                    this.container.classList.remove('panning');
                    this.slider.classList.remove('is-dragging');
                    if (this.dragAbort) { this.dragAbort.abort(); this.dragAbort = null; }
                    if (this.rafId) { cancelAnimationFrame(this.rafId); this.rafId = null; }
                };

                document.addEventListener('mousemove', onMove, { signal: sig });
                document.addEventListener('mouseup', onEnd, { signal: sig });
                document.addEventListener('touchmove', onMove, { signal: sig, passive: false });
                document.addEventListener('touchend', onEnd, { signal: sig });

                if (mode === 'div') this._setPositionFromEvent(clientX, clientY);
            };

            // 分割线手柄拖动
            this.slider.addEventListener('mousedown', (e) => {
                e.preventDefault(); e.stopPropagation();
                onStart(e.clientX, e.clientY, 'div');
            });
            this.slider.addEventListener('touchstart', (e) => {
                if (e.touches.length === 1) { e.stopPropagation(); onStart(e.touches[0].clientX, e.touches[0].clientY, 'div'); }
            }, { passive: true });

            // 画布拖动：仅左键——未放大时拖分割线，放大后拖平移
            //（右键不拦截，避免与浏览器/鼠标手势冲突）
            this.container.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return;
                e.preventDefault();
                onStart(e.clientX, e.clientY, this.mag > this.fitMag * 1.02 ? 'pan' : 'div');
            });
            this.container.addEventListener('touchstart', (e) => {
                if (e.touches.length === 1) {
                    onStart(e.touches[0].clientX, e.touches[0].clientY, this.mag > this.fitMag * 1.02 ? 'pan' : 'div');
                }
            }, { passive: true });
        }

        // ── 缩放（滚轮以光标为中心 / 双指捏合） ──

        _bindZoom() {
            this.viewport.addEventListener('wheel', (e) => {
                e.preventDefault();
                this._applyMag(this.mag * (e.deltaY < 0 ? 1.18 : 1 / 1.18), e.clientX, e.clientY);
            }, { passive: false });

            let lastTouchDist = 0;
            this.viewport.addEventListener('touchstart', (e) => {
                if (e.touches.length === 2) {
                    const dx = e.touches[0].clientX - e.touches[1].clientX;
                    const dy = e.touches[0].clientY - e.touches[1].clientY;
                    lastTouchDist = Math.sqrt(dx * dx + dy * dy);
                }
            }, { passive: true });
            this.viewport.addEventListener('touchmove', (e) => {
                if (e.touches.length === 2) {
                    e.preventDefault();
                    const dx = e.touches[0].clientX - e.touches[1].clientX;
                    const dy = e.touches[0].clientY - e.touches[1].clientY;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (lastTouchDist > 0) this._applyMag(this.mag * (dist / lastTouchDist));
                    lastTouchDist = dist;
                }
            }, { passive: false });
            this.viewport.addEventListener('touchend', () => { lastTouchDist = 0; }, { passive: true });
        }

        // ── 键盘（固定 60px 屏幕步长平移 / +/- 缩放 / F 适配 / Home 重置 / 0 1:1 / H·V 方向） ──

        _bindKeyboard() {
            this.viewport.addEventListener('keydown', (e) => {
                const STEP = 60;
                switch (e.key) {
                    case 'ArrowLeft': e.preventDefault(); this.tx += STEP; this._applyTransform(); break;
                    case 'ArrowRight': e.preventDefault(); this.tx -= STEP; this._applyTransform(); break;
                    case 'ArrowUp': e.preventDefault(); this.ty += STEP; this._applyTransform(); break;
                    case 'ArrowDown': e.preventDefault(); this.ty -= STEP; this._applyTransform(); break;
                    case '+': case '=': e.preventDefault(); this._applyMag(this.mag * 1.18); break;
                    case '-': case '_': e.preventDefault(); this._applyMag(this.mag / 1.18); break;
                    case 'f': case 'F': e.preventDefault(); this._fit(); break;
                    case 'Home': e.preventDefault(); this._resetView(); break;
                    case '0': e.preventDefault(); this._oneToOne(); break;
                    case 'h': case 'H': e.preventDefault(); this.setMode('horizontal'); break;
                    case 'v': case 'V': e.preventDefault(); this.setMode('vertical'); break;
                    case 'End': e.preventDefault(); this._updateSliderUI(1); break;
                }
            });
        }

        // ── 双击：适配 ↔ 1:1 ──

        _bindDoubleClick() {
            this.viewport.addEventListener('dblclick', () => {
                if (this.mag > this.fitMag * 1.02) this._fit();
                else this._oneToOne();
            });
        }

        // ── 工具栏 ──

        _bindToolbar() {
            const btnH = document.getElementById('btnCompareHorizontal');
            const btnV = document.getElementById('btnCompareVertical');
            const btnZoomIn = document.getElementById('btnCompareZoomIn');
            const btnZoomOut = document.getElementById('btnCompareZoomOut');
            const btnFit = document.getElementById('btnCompareFit');
            const btnReset = document.getElementById('btnCompareReset');
            const label = document.getElementById('compareZoomLabel');

            if (btnH) btnH.addEventListener('click', () => this.setMode('horizontal'));
            if (btnV) btnV.addEventListener('click', () => this.setMode('vertical'));
            if (btnZoomIn) btnZoomIn.addEventListener('click', () => this._applyMag(this.mag * 1.18));
            if (btnZoomOut) btnZoomOut.addEventListener('click', () => this._applyMag(this.mag / 1.18));
            if (btnFit) btnFit.addEventListener('click', () => this._fit());
            if (btnReset) btnReset.addEventListener('click', () => this._resetView());
            if (label) label.addEventListener('click', () => this._oneToOne());
        }

        setMode(mode) {
            this.mode = mode;
            const btnH = document.getElementById('btnCompareHorizontal');
            const btnV = document.getElementById('btnCompareVertical');
            if (btnH) btnH.classList.toggle('active', mode === 'horizontal');
            if (btnV) btnV.classList.toggle('active', mode === 'vertical');

            if (mode === 'vertical') {
                this.container.classList.add('vertical');
                const icon = this.slider.querySelector('i');
                if (icon) { icon.className = 'bi bi-arrows-expand-vertical'; }
            } else {
                this.container.classList.remove('vertical');
                const icon = this.slider.querySelector('i');
                if (icon) { icon.className = 'bi bi-arrows-expand-horizontal'; }
            }
            this._updateSliderUI(this.position);
            saveViewPrefs({ dir: mode });
        }

        // ── 放大镜（局部放大，跟随鼠标） ──

        _bindMagnifier() {
            this.viewport.addEventListener('mousemove', (e) => this._updateMagnifier(e));
            this.viewport.addEventListener('mouseleave', () => { if (this.loupe) this.loupe.hidden = true; });
        }

        _updateMagnifier(e) {
            if (!this.magnifierOn || !this.loupe) return;
            const r = this.viewport.getBoundingClientRect();
            const mx = e.clientX - r.left, my = e.clientY - r.top;
            const lensW = this.loupe.clientWidth || 190, lensH = this.loupe.clientHeight || 190;
            const baseL = this.container.offsetLeft, baseT = this.container.offsetTop;
            const imgX = (mx - baseL - this.tx) / this.mag;
            const imgY = (my - baseT - this.ty) / this.mag;
            const w = this.container.offsetWidth, h = this.container.offsetHeight;
            const nx = imgX / w * this.natW, ny = imgY / h * this.natH;
            const dispScale = (this.mag / this.oneToOneMag) * 2;
            if (this.mgBefore) setLoupeLayer(this.mgBefore, this.beforeSrc, this.natW, this.natH, dispScale, nx, ny, lensW, lensH);
            if (this.mgAfter) {
                setLoupeLayer(this.mgAfter, this.afterSrc, this.natW, this.natH, dispScale, nx, ny, lensW, lensH);
                this.mgAfter.style.clipPath = this.mode === 'horizontal'
                    ? `inset(0 0 0 ${this.position * 100}%)`
                    : `inset(${this.position * 100}% 0 0 0)`;
            }
            this.loupe.style.left = `${mx - lensW / 2}px`;
            this.loupe.style.top = `${my - lensH / 2}px`;
            this.loupe.hidden = false;
        }

        setMagnifier(on) {
            this.magnifierOn = !!on;
            if (this.loupe) this.loupe.hidden = !on;
            saveViewPrefs({ magnifier: !!on });
        }

        // ── 图片加载状态 & 对齐计算 ──

        _bindImageLoad() {
            const beforeImg = document.getElementById('compareBefore');
            const afterImg = document.getElementById('compareAfterImg');
            // 每次初始化先回退到文档流模式，保证图片可见
            this.container.classList.remove('is-aligned');
            this.container.style.aspectRatio = '';
            this.container.style.width = '';
            this.container.style.height = '';
            this.container.style.minHeight = '';
            this.container.style.transform = '';

            this._tryAlign = () => {
                const bOK = beforeImg && beforeImg.complete && beforeImg.naturalWidth > 0;
                const aOK = afterImg && afterImg.complete && afterImg.naturalWidth > 0;
                if (!bOK || !aOK) return;

                const ref = beforeImg;
                const ratio = ref.naturalWidth / ref.naturalHeight;
                if (!ratio || !isFinite(ratio)) return;

                const vp = this.viewport;
                const vpRect = vp.getBoundingClientRect();
                const maxW = Math.max(200, vpRect.width - 8);
                const maxH = Math.max(200, vpRect.height - 8);

                let w = maxW;
                let h = w / ratio;
                if (h > maxH) { h = maxH; w = h * ratio; }

                this.container.style.aspectRatio = `${ratio}`;
                this.container.style.width = `${w}px`;
                this.container.classList.add('is-aligned');

                // 1:1 原像素所需倍率（适配尺寸 → 自然像素）
                this.fitMag = 1;
                this.oneToOneMag = Math.max(1, ref.naturalWidth / w);
                this.natW = ref.naturalWidth;
                this.natH = ref.naturalHeight;
                this.beforeSrc = beforeImg.src;
                this.afterSrc = afterImg ? afterImg.src : beforeImg.src;
                this._fit();

                requestAnimationFrame(() => {
                    this._updateSliderUI(this.position);
                    this._applyTransform();
                });
            };

            [beforeImg, afterImg].forEach((img) => {
                if (!img) return;
                const onReady = () => this._tryAlign && this._tryAlign();
                if (img.complete && img.naturalWidth > 0) onReady();
                else { img.addEventListener('load', onReady); img.addEventListener('error', onReady); }
            });

            // 响应式：窗口尺寸 / 侧边栏折叠 导致 viewport 尺寸变化时重新计算
            if (!this._alignCleanup) {
                let raf = 0;
                const onResize = () => {
                    cancelAnimationFrame(raf);
                    raf = requestAnimationFrame(() => this._tryAlign && this._tryAlign());
                };
                window.addEventListener('resize', onResize);
                let ro = null;
                if (typeof ResizeObserver !== 'undefined') {
                    ro = new ResizeObserver(onResize);
                    ro.observe(this.viewport);
                }
                this._alignCleanup = () => {
                    cancelAnimationFrame(raf);
                    window.removeEventListener('resize', onResize);
                    if (ro) ro.disconnect();
                };
            }
        }

        destroy() {
            if (this.dragAbort) this.dragAbort.abort();
            if (this.rafId) cancelAnimationFrame(this.rafId);
            if (this._alignCleanup) {
                this._alignCleanup();
                this._alignCleanup = null;
            }
        }
    }

    // ===== 设置页面 =====
    /**
     * @function switchSettingsTab
     * @description 切换设置页面的标签页，更新导航高亮状态和ARIA属性
     * @param {HTMLElement} el - 被点击的标签导航元素
     * @param {string} sectionName - 目标内容区域名称
     * @returns {void}
     */
    function switchSettingsTab(el, sectionName) {
        // 更新导航高亮和ARIA无障碍属性
        document.querySelectorAll('#settingsNav .nav-item').forEach(item => {
            item.classList.remove('active');
            item.setAttribute('aria-selected', 'false');
            item.setAttribute('tabindex', '-1');
        });
        el.classList.add('active');
        el.setAttribute('aria-selected', 'true');
        el.setAttribute('tabindex', '0');

        // 切换内容区域显示
        document.querySelectorAll('.sv-settings-section').forEach(section => {
            section.style.display = 'none';
        });
        const target = document.getElementById(`section-${sectionName}`);
        if (target) target.style.display = 'block';
    }

    /**
     * @function initSettingsTabKeyboardNav
     * @description 初始化设置页面标签的键盘导航（左右方向键、Home/End键切换标签，支持无障碍访问）
     * @returns {void}
     */
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

    /**
     * @function loadSettings
     * @description 从服务器加载系统设置并填充到设置表单
     * @returns {Promise<void>}
     */
    async function loadSettings() {
        try {
            const settings = await api.get('/api/system/settings');

            // 填充模型设置
            if (settings.model) {
                const modelSize = document.getElementById('defaultModelSize');
                if (modelSize) modelSize.value = settings.model.default_size || '3b';

                const modelPrecision = document.getElementById('modelPrecision');
                if (modelPrecision) modelPrecision.value = settings.model.precision || 'fp16';

                const autoLoad = document.getElementById('autoLoad');
                if (autoLoad) autoLoad.checked = settings.model.auto_load !== false;
            }

            // 填充GPU设置
            if (settings.gpu) {
                const gpuBackend = document.getElementById('gpuBackend');
                if (gpuBackend) gpuBackend.value = settings.gpu.backend || 'auto';

                const memoryStrategy = document.getElementById('memoryStrategy');
                if (memoryStrategy) memoryStrategy.value = settings.gpu.memory_strategy || 'balanced';

                const enableFp16 = document.getElementById('enableFp16');
                if (enableFp16) enableFp16.checked = settings.gpu.enable_fp16 !== false;
            }

            // 填充语言设置
            if (settings.i18n) {
                const locale = document.getElementById('locale');
                if (locale) locale.value = settings.i18n.default_locale || 'zh';
            }
        } catch (err) {
            console.error('Load settings failed:', err);
        }
    }

    // ===== 历史记录 =====
    /**
     * @function deleteHistoryRecord
     * @description 删除历史记录，弹出确认对话框后执行删除操作
     * @param {string} id - 历史记录ID
     * @returns {void}
     */
    async function deleteHistoryRecord(id) {
        confirm(t('history.delete_confirm_title'), t('history.delete_confirm_msg'), async () => {
            try {
                await api.delete(`/api/system/history/${id}`);
                toast(t('history.record_deleted'), 'success');
                // 触发页面刷新
                const btnRefresh = document.getElementById('btnRefresh');
                if (btnRefresh) btnRefresh.click();
            } catch (err) {
                toast(t('history.delete_failed') + ': ' + err.message, 'error');
            }
        });
    }

    /**
     * @function clearHistoryWithOptions
     * @description Show a clear history dialog with a checkbox option for completed records.
     * @returns {Promise<{includeCompleted: boolean, cancelled: boolean}>}
     */
    async function clearHistoryWithOptions() {
        const I = window.__I18N__ || {};
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'sv-modal-overlay';
            overlay.id = 'clearHistoryModal';
            overlay.style.display = 'flex';
            overlay.innerHTML = (
                '<div class="sv-modal" style="max-width:420px;">' +
                '<div class="sv-modal-header">' +
                '<h3>' + (I["history.clear"] || 'Clear History') + '</h3>' +
                '<button class="sv-btn sv-btn-icon sv-btn-outline" aria-label="Close" data-modal-close="clearHistoryModal">' +
                '<i class="bi bi-x"></i></button>' +
                '</div>' +
                '<div class="sv-modal-body">' +
                '<p style="margin-bottom:14px;">' + (I["history.clear_confirm"] || 'This will clear failed, pending, and processing records.') + '</p>' +
                '<label class="sv-param-check" style="display:flex;align-items:center;gap:8px;cursor:pointer;">' +
                '<input type="checkbox" id="cbIncludeCompleted" style="width:18px;height:18px;accent-color:var(--sv-primary);">' +
                '<span style="font-size:0.85rem;">' + (I["history.clear_include_completed"] || 'Also clear completed records') + '</span>' +
                '</label>' +
                '</div>' +
                '<div class="sv-modal-footer">' +
                '<button class="sv-btn sv-btn-secondary" data-modal-close="clearHistoryModal">' + (I["common.cancel"] || 'Cancel') + '</button>' +
                '<button class="sv-btn sv-btn-danger" id="btnDoClearHistory">' + (I["common.confirm"] || 'Confirm') + '</button>' +
                '</div>' +
                '</div>'
            );
            document.body.appendChild(overlay);
            overlay.classList.add('show');

            const close = () => {
                overlay.classList.remove('show');
                overlay.remove();
                resolve({ includeCompleted: false, cancelled: true });
            };

            overlay.querySelectorAll('[data-modal-close="clearHistoryModal"]').forEach(function(b) {
                b.addEventListener('click', close);
            });
            overlay.addEventListener('click', function(e) {
                if (e.target === overlay) close();
            });

            document.getElementById('btnDoClearHistory').addEventListener('click', function() {
                var includeCompleted = document.getElementById('cbIncludeCompleted').checked;
                overlay.classList.remove('show');
                overlay.remove();
                resolve({ includeCompleted: includeCompleted, cancelled: false });
            });
        });
    }

    // ===== 重置修复页面 =====
    /**
     * @function resetRestore
     * @description 重置修复页面状态，清除上传文件、进度条、结果显示，关闭SSE连接
     * @returns {void}
     */
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
        const plainViewer = document.getElementById('plainViewer');
        if (plainViewer) plainViewer.style.display = 'none';
        const videoCc = document.getElementById('videoCompareCard');
        const videoPv = document.getElementById('videoPlainViewer');
        const vBefore = document.getElementById('videoCompareBefore');
        const vAfter = document.getElementById('videoCompareAfterImg');
        if (videoCc) { videoCc.style.display = 'none'; }
        if (videoPv) { videoPv.style.display = 'none'; }
        if (vBefore) { vBefore.removeAttribute('src'); vBefore.load && vBefore.load(); }
        if (vAfter) { vAfter.removeAttribute('src'); vAfter.load && vAfter.load(); }
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

        // 重置进度条（使用transform:scaleX提升性能）
        const progressBar = document.getElementById('progressBar');
        if (progressBar) {
            progressBar.style.transform = 'scaleX(0)';
            progressBar.classList.add('animated');
            progressBar.classList.remove('bg-success');
            progressBar.classList.add('bg-primary');
            progressBar.setAttribute('aria-valuenow', '0');
        }

        // 关闭修复进度SSE连接
        if (currentRestoreEventSource) {
            currentRestoreEventSource.close();
            currentRestoreEventSource = null;
        }

        // 重置一体化工具条：全部操作组回到禁用态
        ['btnDownload', 'btnRestoreAgain', 'btnCanvasClear', 'btnCanvasReplace', 'btnCanvasCompare', 'btnMagnifier',
         'btnCompareHorizontal', 'btnCompareVertical', 'btnCompareZoomIn', 'btnCompareZoomOut', 'btnCompareFit', 'btnCompareReset']
            .forEach((id) => {
                const b = document.getElementById(id);
                if (b) b.setAttribute('disabled', '');
            });
        const cmpToggle = document.getElementById('btnCanvasCompare');
        if (cmpToggle) cmpToggle.classList.remove('active');
        const mgBtn = document.getElementById('btnMagnifier');
        if (mgBtn) mgBtn.classList.remove('active');
        const zoomLabel = document.getElementById('compareZoomLabel');
        if (zoomLabel) zoomLabel.textContent = '—';
        const hud = document.getElementById('compareHud');
        if (hud) hud.textContent = '—';
        const previewHud = document.getElementById('previewHud');
        if (previewHud) previewHud.textContent = '—';
        const errorCard = document.getElementById('errorCard');
        if (errorCard) errorCard.style.display = 'none';
        const resultMetaText = document.getElementById('resultMetaText');
        if (resultMetaText) { resultMetaText.style.display = 'none'; resultMetaText.textContent = ''; }
        const tbFileName = document.getElementById('tbFileName');
        if (tbFileName) { tbFileName.style.display = 'none'; tbFileName.textContent = ''; }
        // 关闭放大镜与预览查看器状态
        if (activeCompareSlider) { try { activeCompareSlider.setMagnifier(false); } catch (e) { /* ignore */ } }
        if (activePreviewViewer) { try { activePreviewViewer.setMagnifier(false); } catch (e) { /* ignore */ } }

        // 清除持久化的修复会话
        try { localStorage.removeItem('sv_restore_session'); } catch(e) {}
    }

    // ===== 工具函数 =====
    /**
     * @function formatFileSize
     * @description 格式化文件大小为易读的字符串（B/KB/MB/GB/TB）
     * @param {number} bytes - 文件大小（字节）
     * @returns {string} 格式化后的文件大小字符串
     */
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    /**
     * @function formatTimestamp
     * @description 格式化ISO时间戳为本地化的日期时间字符串
     * @param {string} isoString - ISO格式的时间字符串
     * @returns {string} 本地化的日期时间字符串
     */
    function formatTimestamp(isoString) {
        if (!isoString) return '--';
        try {
            const date = new Date(isoString);
            const localeMap = { zh: 'zh-CN', 'zh-TW': 'zh-TW', en: 'en-US', ja: 'ja-JP', fr: 'fr-FR' };
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

    /**
     * @function formatUptime
     * @description 格式化运行时间（秒）为天/时/分/秒格式
     * @param {number} seconds - 运行时间（秒）
     * @returns {string} 格式化后的运行时间字符串
     */
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

    /**
     * @function formatDuration
     * @description 格式化预估持续时间（秒）为易读格式（秒/分/小时）
     * @param {number} seconds - 持续时间（秒）
     * @returns {string} 格式化后的持续时间字符串
     */
    function formatDuration(seconds) {
        if (seconds < 60) return `${Math.round(seconds)}${t('time.second')}`;
        if (seconds < 3600) return `${Math.round(seconds / 60)}${t('time.minute')}`;
        return `${(seconds / 3600).toFixed(1)}${t('time.hour')}`;
    }

    // ===== 设置页控件绑定（settings.html 左设置右关于改版） =====
    /**
     * @function initSettingsPageControls
     * @description 绑定设置页语言/主题下拉的行为：语言切换复用 switchLocale，
     *              主题切换复用 applyTheme 并持久化到 localStorage。
     * @returns {void}
     */
    function initSettingsPageControls() {
        const localeSelect = document.getElementById('settingsLocale');
        if (localeSelect) {
            localeSelect.addEventListener('change', () => {
                switchLocale(localeSelect.value);
            });
        }
        const themeSelect = document.getElementById('settingsTheme');
        if (themeSelect) {
            const current = document.documentElement.getAttribute('data-theme') || 'dark';
            themeSelect.value = current === 'light' ? 'light' : 'dark';
            themeSelect.addEventListener('change', () => {
                applyTheme(themeSelect.value);
                try { localStorage.setItem('sv-theme', themeSelect.value); } catch (e) { /* ignore */ }
            });
        }
    }

    // ===== 语言切换下拉菜单 =====
    /**
     * @constant {string[]} LOCALE_ORDER
     * @description 支持的语言代码列表，按显示顺序排列
     * @default ['zh', 'zh-TW', 'en', 'ja', 'fr']
     */
    const LOCALE_ORDER = ['zh', 'zh-TW', 'en', 'ja', 'fr'];

    /**
     * @function switchLocale
     * @description 切换界面语言，调用API后刷新页面
     * @param {string} localeCode - 语言代码（zh/zh-TW/en/ja/fr）
     * @returns {Promise<void>}
     */
    async function switchLocale(localeCode) {
        try {
            const data = await api.post('/api/system/locale', { locale: localeCode });
            toast(data.message || t('locale.switched'), 'success');
            // 显示过渡遮罩层，实现平滑刷新效果
            const overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;inset:0;background:var(--sv-bg,rgba(15,20,15,0.95));z-index:9999;opacity:0;transition:opacity 0.2s ease;display:flex;align-items:center;justify-content:center;';
            const spinner = document.createElement('span');
            spinner.className = 'sv-spinner';
            spinner.style.cssText = 'width:32px;height:32px;';
            overlay.appendChild(spinner);
            document.body.appendChild(overlay);
            requestAnimationFrame(() => { overlay.style.opacity = '1'; });
            setTimeout(() => window.location.reload(), 300);
        } catch (err) {
            toast((t('locale.switch_failed') + ': ' + err.message), 'error');
        }
    }

    // ===== 历史记录右键菜单 =====
    /**
     * @var {string|null} _contextMenuRecordId
     * @description 当前右键菜单关联的历史记录ID
     * @private
     */
    let _contextMenuRecordId = null;
    /**
     * @var {string|null} _contextMenuOutputPath
     * @description 当前右键菜单关联的输出文件路径
     * @private
     */
    let _contextMenuOutputPath = null;

    /**
     * @function showRowContextMenu
     * @description 显示历史记录行的右键上下文菜单
     * @param {MouseEvent} event - 鼠标右键事件对象
     * @param {HTMLElement} row - 历史记录行元素（需包含data-record-id和data-output属性）
     * @returns {void}
     */
    function showRowContextMenu(event, row) {
        event.preventDefault();
        const menu = document.getElementById('svContextMenu');
        if (!menu) return;

        _contextMenuRecordId = row.dataset ? row.dataset.recordId : row.getAttribute?.('data-record-id');
        _contextMenuOutputPath = row.dataset ? row.dataset.output : row.getAttribute?.('data-output');

        const openBtn = document.getElementById('ctxOpenOutputDir');
        if (openBtn) {
            openBtn.disabled = !_contextMenuOutputPath;
        }

        menu.style.left = `${event.clientX}px`;
        menu.style.top = `${event.clientY}px`;
        menu.classList.add('show');
        menu.setAttribute('aria-hidden', 'false');
    }

    /**
     * @function closeContextMenu
     * @description 关闭右键上下文菜单
     * @returns {void}
     */
    function closeContextMenu() {
        const menu = document.getElementById('svContextMenu');
        if (menu) {
            menu.classList.remove('show');
            menu.setAttribute('aria-hidden', 'true');
        }
    }

    /**
     * @function getOutputDir
     * @description 从文件路径中提取目录部分（规范化路径分隔符）
     * @param {string} path - 文件完整路径
     * @returns {string} 目录路径
     */
    function getOutputDir(path) {
        if (!path) return '';
        const normalized = path.replace(/\\/g, '/');
        const lastSlash = normalized.lastIndexOf('/');
        return lastSlash > 0 ? normalized.substring(0, lastSlash) : normalized;
    }

    // ===== 初始化 =====
    /**
     * @function init
     * @description 应用初始化函数，在DOM加载完成后执行，初始化所有组件和事件监听
     * @returns {void}
     */
    function init() {
        // 初始化主题
        initTheme();

        // 初始化全局SSE连接
        initGlobalSSE();

        // 初始化语言切换下拉菜单
        initLocaleDropdown();

        // 系统状态栏折叠/展开（默认收起为状态点，hover展开，点击锁定展开）
        const sysToggle = document.getElementById('sysWidgetToggle');
        const sysBody = document.getElementById('sysWidgetBody');
        const sysWidget = sysToggle ? sysToggle.closest('.sv-sys-widget') : null;
        let sysPinned = false;

        /**
         * @function setSysExpanded
         * @description 设置系统状态栏展开/折叠状态
         * @param {boolean} expanded - 是否展开
         * @param {boolean} [pin] - 是否锁定展开状态
         * @returns {void}
         */
        function setSysExpanded(expanded, pin) {
            if (!sysBody || !sysWidget) return;
            if (pin !== undefined) sysPinned = pin;
            sysBody.classList.toggle('collapsed', !expanded);
            sysWidget.classList.toggle('collapsed', !expanded);
            const icon = sysToggle.querySelector('i');
            if (icon) icon.className = expanded ? 'bi bi-chevron-down' : 'bi bi-chevron-up';
        }

        if (sysToggle && sysBody && sysWidget) {
            // 初始化：确保默认折叠状态
            setSysExpanded(false, false);

            let sysCollapseTimer = null;

            // 点击切换锁定状态
            sysToggle.addEventListener('click', (e) => {
                e.stopPropagation();
                if (sysCollapseTimer) {
                    clearTimeout(sysCollapseTimer);
                    sysCollapseTimer = null;
                }
                const isCollapsed = sysBody.classList.contains('collapsed');
                setSysExpanded(isCollapsed, isCollapsed);
            });

            // hover自动展开（非锁定状态）
            sysWidget.addEventListener('mouseenter', () => {
                if (sysCollapseTimer) {
                    clearTimeout(sysCollapseTimer);
                    sysCollapseTimer = null;
                }
                if (!sysPinned) setSysExpanded(true, false);
            });
            sysWidget.addEventListener('mouseleave', () => {
                if (!sysPinned) {
                    // 添加延迟，防止鼠标在边缘移动时频繁闪烁
                    sysCollapseTimer = setTimeout(() => {
                        setSysExpanded(false, false);
                        sysCollapseTimer = null;
                    }, 200);
                }
            });
        }

        // HTMX全局错误联动Toast
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

            // 后端通过HX-Trigger: showToast触发的事件
            document.body.addEventListener('showToast', (evt) => {
                if (evt.detail) {
                    toast(evt.detail.message, evt.detail.type || 'info');
                }
            });
        }

        // 高亮当前导航项
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
            /**
             * @function closeMobileNav
             * @description 关闭移动端导航菜单
             * @returns {void}
             */
            function closeMobileNav() {
                mainNav.classList.remove('show');
                if (mobileNavOverlay) mobileNavOverlay.classList.remove('show');
            }

            /**
             * @function toggleMobileNav
             * @description 切换移动端导航菜单显示/隐藏
             * @returns {void}
             */
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

        // ESC键关闭模态框与右键菜单
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.sv-modal-overlay.show').forEach(modal => {
                    closeModal(modal.id);
                });
                closeContextMenu();
            }
        });

        // Data attribute模态框关闭按钮
        document.querySelectorAll('[data-modal-close]').forEach(btn => {
            btn.addEventListener('click', () => {
                const modalId = btn.getAttribute('data-modal-close');
                closeModal(modalId);
            });
        });

        // 键盘快捷键：Alt+数字直达导航
        // 不使用Ctrl+数字（浏览器标签页切换冲突）
        // Alt+数字在键盘上横向连续，手部移动距离最短
        // 注意：Windows下Alt键会激活菜单栏，需在keydown阶段阻止默认行为
        /**
         * @constant {Object} NAV_SHORTCUTS
         * @description 导航快捷键映射，Alt+数字键对应不同页面
         */
        const NAV_SHORTCUTS = {
            '1': { path: '/', label: '首页' },
            '2': { path: '/restore', label: '修复' },
            '3': { path: '/history', label: '历史记录' },
            '4': { path: '/settings', label: '设置' },
        };

        /**
         * @function isInputFocused
         * @description 检查当前焦点是否在输入元素上（避免快捷键与输入冲突）
         * @returns {boolean} 是否在输入元素上
         */
        function isInputFocused() {
            const el = document.activeElement;
            if (!el) return false;
            const tag = el.tagName;
            return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
        }

        // 在keydown阶段（捕获阶段）阻止Alt键激活菜单栏，并处理快捷键
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

        // 更新Widget内存进度条
        /**
         * @function updateWidgetMemory
         * @description 更新系统状态栏内存使用进度条
         * @returns {Promise<void>}
         */
        async function updateWidgetMemory() {
            try {
                const health = await api.get('/api/system/health');
                if (health.system && health.system.memory_total_gb > 0) {
                    const total = health.system.memory_total_gb;
                    const avail = health.system.memory_available_gb;
                    const usedPct = Math.round(((total - avail) / total) * 100);
                    const fillEl = document.getElementById('statusMemFill');
                    const textEl = document.getElementById('statusMemText');
                    if (fillEl) fillEl.style.transform = 'scaleX(' + (usedPct / 100) + ')';
                    if (textEl) textEl.textContent = usedPct + '%';
                }
            } catch (e) { /* ignore */ }
        }
        updateWidgetMemory();

        // 定期更新状态栏时间（i18n格式）
        const localeMap = { zh: 'zh-CN', 'zh-TW': 'zh-TW', en: 'en-US', ja: 'ja-JP', fr: 'fr-FR' };
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


        // ===== 修复页面持久化会话 =====
        // 页面卸载/切页前保存当前修复状态
        window.addEventListener('pagehide', function() {
            saveRestoreSession();
        });
        window.addEventListener('beforeunload', function() {
            saveRestoreSession();
        });
        // 页面切回时恢复会话
        document.addEventListener('DOMContentLoaded', function() {
            if (document.getElementById('restoreUploadZone') ||
                document.getElementById('previewArea')) {
                setTimeout(function() { restoreRestoreSession(); }, 50);
            }
        });
        // 每5秒自动保存进度快照（仅处理中时有效）
        setInterval(function() {
            var pc = document.getElementById('progressCard');
            if (pc && pc.style.display !== 'none') saveRestoreSession();
        }, 5000);

        // 表单验证
        initFormValidation();

        // Shrink参数联动
        initShrinkToggle();

        // 设置页面Tab键盘导航
        initSettingsTabKeyboardNav();

        // 设置页语言/主题下拉行为绑定（settings.html 改版后）
        initSettingsPageControls();

        // 移动端参数面板折叠
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
    /**
     * @function initLocaleDropdown
     * @description 初始化语言切换下拉菜单，处理点击切换、外部点击关闭、ESC关闭
     * @returns {void}
     */
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

        // ESC关闭菜单
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && menu.classList.contains('show')) {
                menu.classList.remove('show');
                btn.setAttribute('aria-expanded', 'false');
                btn.focus();
            }
        });
    }

    // ===== 主题管理 =====
    /**
     * @function initTheme
     * @description 初始化主题切换功能，从LocalStorage读取保存的主题，默认暗色主题
     * @returns {void}
     */
    function initTheme() {
        // 与base.html内联脚本保持一致：默认暗色主题，仅当用户明确选择过才使用保存的主题
        // 不使用prefers-color-scheme自动切换，避免与用户手动选择冲突
        const saved = localStorage.getItem('sv-theme');
        const theme = saved || 'dark';
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

    /**
     * @function applyTheme
     * @description 应用指定主题，设置data-theme属性并更新主题切换按钮图标
     * @param {string} theme - 主题名称：'dark' 或 'light'
     * @returns {void}
     */
    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        const icon = document.getElementById('themeIcon');
        if (icon) {
            icon.className = theme === 'dark' ? 'bi bi-moon-stars-fill' : 'bi bi-sun-fill';
        }
    }

    // ===== Shrink 参数联动 =====
    /**
     * @function initShrinkToggle
     * @description 初始化Shrink（缩放）参数联动，启用/禁用复选框控制相关参数的禁用状态
     * @returns {void}
     */
    function initShrinkToggle() {
        const shrinkEnabled = document.getElementById('shrink_enabled');
        const shrinkAlgorithm = document.getElementById('shrink_algorithm');
        const shrinkScale = document.getElementById('shrink_scale');

        if (!shrinkEnabled || !shrinkAlgorithm) return;

        /**
         * @function updateShrinkState
         * @description 根据复选框状态更新相关参数的禁用状态
         * @returns {void}
         */
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

    // ===== 表单验证 =====
    /**
     * @function initFormValidation
     * @description 初始化表单验证，为数值类型输入框添加范围验证，实时显示错误提示
     * @returns {void}
     */
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
                    errorMsg = t('form.min_value', {min});
                }
                if (!isNaN(max) && val > max) {
                    errorMsg = t('form.max_value', {max});
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

    // DOM加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // ===== 目录浏览器 =====
    /**
     * @var {Function|null} _dirBrowserCallback
     * @description 目录浏览器选择完成后的回调函数
     * @private
     */
    let _dirBrowserCallback = null;

    /**
     * @function openDirBrowser
     * @description 打开目录浏览器模态框，支持目录导航、选择、打开资源管理器
     * @param {string} currentPath - 初始显示的目录路径
     * @param {Function} callback - 选择目录后的回调函数，参数为选中的目录路径
     * @returns {void}
     */
    function openDirBrowser(currentPath, callback) {
        _dirBrowserCallback = callback;
        const pathInput = document.getElementById('dirBrowserPathInput');
        pathInput.value = currentPath || '';
        SeedVR2.openModal('dirBrowserModal');
        loadDirListing(currentPath || '');

        // Go按钮：跳转到指定路径
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
        // Enter键快速跳转
        pathInput.onkeydown = (e) => {
            if (e.key === 'Enter') loadDirListing(pathInput.value.trim());
        };
        // 选择按钮：确认选择并关闭
        document.getElementById('dirBrowserSelectBtn').onclick = () => {
            const selected = pathInput.value.trim();
            if (selected && _dirBrowserCallback) {
                _dirBrowserCallback(selected);
            }
            SeedVR2.closeModal('dirBrowserModal');
        };
    }

    /**
     * @function loadDirListing
     * @description 加载指定路径的目录列表，显示驱动器、文件夹、父目录导航
     * @param {string} path - 要加载的目录路径
     * @returns {Promise<void>}
     * @private
     */
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

            // 父目录导航项（..)
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

            // 目录和驱动器列表
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

            // 空目录提示
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

    /**
     * @function escapeHtml
     * @description HTML转义函数，防止XSS攻击，将特殊字符转换为HTML实体
     * @param {string} str - 要转义的字符串
     * @returns {string} 转义后的HTML安全字符串
     */
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ===== 用户偏好持久化 =====
    /**
     * @function loadUserPreferences
     * @description 从服务器加载用户UI偏好设置
     * @returns {Promise<Object|null>} 用户偏好数据对象，加载失败返回null
     */
    async function loadUserPreferences() {
        try {
            const data = await api.get('/api/ui/preferences');
            if (data.success && data.data) {
                return data.data;
            }
        } catch (e) {
            console.debug('Load user preferences failed:', e);
        }
        return null;
    }

    /**
     * @function saveUserPreferences
     * @description 保存用户UI偏好设置到服务器
     * @param {Object} values - 要保存的偏好设置键值对
     * @returns {Promise<boolean>} 保存是否成功
     */
    async function saveUserPreferences(values) {
        try {
            const data = await api.post('/api/ui/preferences', values);
            return data.success;
        } catch (e) {
            console.error('Save user preferences failed:', e);
            return false;
        }
    }

    /**
     * @function loadRestorePrefs
     * @description 加载修复页最后一次保存的表单值 + 解锁状态快照
     * @returns {Promise<{values: Object, unlock_state: Object}|null>}
     */
    async function loadRestorePrefs() {
        try {
            const data = await api.get('/api/ui/restore-preferences');
            if (data.success && data.data) {
                return {
                    values: data.data.values || {},
                    unlock_state: data.data.unlock_state || {},
                };
            }
        } catch (e) {
            console.debug('Load restore preferences failed:', e);
        }
        return null;
    }

    /**
     * @function saveRestorePrefs
     * @description 增量保存修复页表单值和/或解锁状态（浅 merge，不会清空其他字段）
     * @param {Object} [payload]
     * @param {Object} [payload.values]  {form_name: value} 只传变更字段即可
     * @param {Object} [payload.unlock_state]  {form_name: true/false}
     * @returns {Promise<{values: Object, unlock_state: Object}|null>} 保存后完整快照；失败返回 null
     */
    async function saveRestorePrefs(payload) {
        try {
            const data = await api.post('/api/ui/restore-preferences', payload || {});
            if (data.success && data.data) {
                return {
                    values: data.data.values || {},
                    unlock_state: data.data.unlock_state || {},
                };
            }
        } catch (e) {
            console.error('Save restore preferences failed:', e);
        }
        return null;
    }

    // ===== 卡片显示/隐藏动画 =====
    /**
     * @function showCard
     * @description 显示指定元素并添加淡入动画效果
     * @param {string} elementId - 要显示的元素ID
     * @returns {void}
     */
    function showCard(elementId) {
        const el = document.getElementById(elementId);
        if (!el) return;
        el.style.display = 'block';
        el.classList.add('sv-fade-in');
        setTimeout(() => el.classList.remove('sv-fade-in'), 300);
    }

    /**
     * @function hideCard
     * @description 隐藏指定元素
     * @param {string} elementId - 要隐藏的元素ID
     * @returns {void}
     */
    function hideCard(elementId) {
        const el = document.getElementById(elementId);
        if (!el) return;
        el.style.display = 'none';
    }

    // ===== 按钮 Loading 状态工具 =====
    /**
     * @function setButtonLoading
     * @description 设置按钮为加载状态，显示spinner并禁用交互
     * @param {HTMLButtonElement|string} button - 按钮元素或按钮ID
     * @param {string} [loadingText] - 加载时显示的文本（可选）
     * @returns {Function} 恢复按钮原始状态的函数
     */
    function setButtonLoading(button, loadingText) {
        const btn = typeof button === 'string' ? document.getElementById(button) : button;
        if (!btn) return () => {};

        const originalHTML = btn.innerHTML;
        const originalDisabled = btn.disabled;

        btn.classList.add('loading');
        btn.disabled = true;

        const spinner = document.createElement('span');
        spinner.className = 'sv-spinner-btn';
        btn.innerHTML = '';
        btn.appendChild(spinner);
        if (loadingText) {
            const textSpan = document.createElement('span');
            textSpan.className = 'sv-loading-text';
            textSpan.textContent = loadingText;
            textSpan.style.marginLeft = '24px';
            textSpan.style.color = 'var(--sv-btn-primary-text)';
            btn.appendChild(textSpan);
        }

        return function restoreButton() {
            btn.classList.remove('loading');
            btn.disabled = originalDisabled;
            btn.innerHTML = originalHTML;
        };
    }

    // ===== 公开 API =====
    /**
     * @namespace SeedVR2
     * @description SeedVR2前端模块公开API，供页面内联脚本和其他模块调用
     */
    return {
        /** @type {Object} HTTP API封装对象 */
        api,
        /** @type {Function} i18n翻译函数 */
        t,
        /** @type {Function} HTTP状态码文本获取 */
        httpStatusText,
        /** @type {Function} API错误解析 */
        parseApiError,
        /** @type {Function} Toast通知显示 */
        toast,
        /** @type {Function} 确认对话框 */
        confirm,
        /** @type {Function} 关闭模态框 */
        closeModal,
        /** @type {Function} 打开模态框 */
        openModal,
        /** @type {Function} 设置上传区域 */
        setupUploadZone,
        /** @type {Function} 启动修复进度SSE */
        startRestoreProgressSSE,
        /** @type {Function} 取消修复任务 */
        cancelRestoreTask,
        /** @type {Function} 重置修复页面 */
        resetRestore,
        /** @type {Function} 初始化对比滑块 */
        initCompareSlider,
        /** @type {Function} 初始化图片预览查看器（缩放/拖动/放大镜） */
        initPreviewViewer,
        /** @type {Function} 销毁图片预览查看器 */
        destroyPreviewViewer,
        /** @type {Function} 获取当前对比滑块实例 */
        getActiveCompareSlider,
        /** @type {Function} 获取当前预览查看器实例 */
        getActivePreviewViewer,
        /** @type {Function} 切换设置标签 */
        switchSettingsTab,
        /** @type {Function} 加载设置 */
        loadSettings,
        /** @type {Function} 删除历史记录 */
        deleteHistoryRecord,
        /** @type {Function} 带选项清除历史记录 */
        clearHistoryWithOptions,
        /** @type {Function} 切换语言（别名） */
        cycleLocale: switchLocale,
        /** @type {Function} 切换语言 */
        switchLocale,
        /** @type {Function} 显示行右键菜单 */
        showRowContextMenu,
        /** @type {Function} 打开目录浏览器 */
        openDirBrowser,
        /** @type {Function} 显示卡片（带动画） */
        showCard,
        /** @type {Function} 隐藏卡片 */
        hideCard,
        /** @type {Function} 格式化文件大小 */
        formatFileSize,
        /** @type {Function} 格式化时间戳 */
        formatTimestamp,
        /** @type {Function} 格式化运行时间 */
        formatUptime,
        /** @type {Function} 格式化持续时间 */
        formatDuration,
        /** @type {Function} 初始化主题 */
        initTheme,
        /** @type {Function} 应用主题 */
        applyTheme,
        /** @type {Function} HTML转义 */
        escapeHtml,
        /** @type {Function} 初始化表单验证 */
        initFormValidation,
        /** @type {Function} 获取CSRF Token */
        getCsrfToken,
        /** @type {Function} 获取CSRF请求头 */
        csrfHeaders,
        /** @type {Function} 加载用户偏好 */
        loadUserPreferences,
        /** @type {Function} 保存用户偏好 */
        saveUserPreferences,
        /** @type {Function} 加载修复页表单值+解锁状态快照 */
        loadRestorePrefs,
        /** @type {Function} 增量保存修复页表单值+解锁状态 */
        saveRestorePrefs,
        /** @type {Function} 设置按钮加载状态 */
        setButtonLoading,
        /** @type {Function} 保存修复会话到 localStorage */
        saveRestoreSession,
        /** @type {Function} 从 localStorage 恢复修复会话 */
        restoreRestoreSession,
    };
})();

/* ===== 标题字体切换（14 种免费开源字体，Google Fonts / SIL OFL / Apache 2.0） ===== */
(function () {
    var FONTS = [
        { g: '中文现代', items: [
            { n: '思源黑体', f: '"Noto Sans SC",sans-serif', d: '现代简洁 · 默认' },
            { n: '思源宋体', f: '"Noto Serif SC",serif', d: '优雅衬线' },
            { n: '站酷小薇', f: '"ZCOOL XiaoWei",serif', d: '文艺手写' },
            { n: '站酷庆科黄油体', f: '"ZCOOL QingKe HuangYou",sans-serif', d: '圆润趣味' },
            { n: '站酷快乐体', f: '"ZCOOL KuaiLe",sans-serif', d: '活泼可爱' }
        ]},
        { g: '中文书法', items: [
            { n: '马善政楷书', f: '"Ma Shan Zheng",cursive', d: '毛笔楷书' },
            { n: '龙藏手书', f: '"Long Cang",cursive', d: '手写行书' },
            { n: '志莽行书', f: '"Zhi Mang Xing",cursive', d: '洒脱行书' },
            { n: '柳建茂草书', f: '"Liu Jian Mao Cao",cursive', d: '狂草艺术' }
        ]},
        { g: '西文艺术', items: [
            { n: 'Playfair Display', f: '"Playfair Display",serif', d: '优雅衬线' },
            { n: 'Cinzel', f: '"Cinzel",serif', d: '古典罗马' },
            { n: 'Great Vibes', f: '"Great Vibes",cursive', d: '花体手写' },
            { n: 'Pacifico', f: '"Pacifico",cursive', d: '复古圆润' },
            { n: 'Dancing Script', f: '"Dancing Script",cursive', d: '流畅手写' }
        ]}
    ];
    var menu = document.getElementById('fontMenu');
    var btn = document.getElementById('btnFontSwitch');
    if (!menu || !btn) return;

    function curFont() { try { return localStorage.getItem('sv-font') || ''; } catch (e) { return ''; } }

    function build() {
        menu.innerHTML = '';
        FONTS.forEach(function (grp) {
            var g = document.createElement('div');
            g.className = 'sv-font-group';
            g.textContent = grp.g;
            menu.appendChild(g);
            grp.items.forEach(function (f) {
                var b = document.createElement('button');
                b.className = 'sv-font-item';
                b.setAttribute('role', 'menuitem');
                b.type = 'button';
                b.style.fontFamily = f.f;
                b.dataset.f = f.f;
                b.innerHTML = f.n + '<span class="fd">' + f.d + '</span><span class="fg">' + f.f + '</span>';
                b.addEventListener('click', function () { apply(f.f); });
                menu.appendChild(b);
            });
        });
        sync();
    }

    function apply(f) {
        document.documentElement.style.setProperty('--sv-font', f);
        try { localStorage.setItem('sv-font', f); } catch (e) {}
        sync();
    }

    function sync() {
        var cur = curFont();
        menu.querySelectorAll('.sv-font-item').forEach(function (b) {
            b.classList.toggle('active', b.dataset.f === cur);
        });
    }

    function restore() {
        var saved = curFont();
        if (saved) document.documentElement.style.setProperty('--sv-font', saved);
        sync();
    }

    btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var lm = document.getElementById('localeMenu');
        if (lm) lm.classList.remove('show');
        menu.classList.toggle('show');
        btn.setAttribute('aria-expanded', menu.classList.contains('show'));
    });
    document.addEventListener('click', function (e) {
        if (!e.target.closest('#fontDropdown')) {
            menu.classList.remove('show');
            btn.setAttribute('aria-expanded', 'false');
        }
    });
    build();
    restore();
})();

