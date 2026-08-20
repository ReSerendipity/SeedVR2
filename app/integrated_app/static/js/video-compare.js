/**
 * @file 视频前后对比查看器
 * @description 为视频修复结果提供前后对比功能
 */
(function() {
    'use strict';
    let activeVideoCompareSlider = null;

    window.initVideoCompareSlider = function(taskId, videoSrc) {
        if (activeVideoCompareSlider) activeVideoCompareSlider.destroy();
        activeVideoCompareSlider = new VideoCompareSlider('videoCompareContainer', 'videoCompareSlider', 'videoCompareAfter');
        return activeVideoCompareSlider;
    };

    class VideoCompareSlider {
        constructor(containerId, sliderId, afterId) {
            this.container = document.getElementById(containerId);
            this.slider = document.getElementById(sliderId);
            this.afterEl = document.getElementById(afterId);
            if (!this.container || !this.slider || !this.afterEl) return;
            this.viewport = this.container.parentElement;
            this.beforeVideo = document.getElementById(containerId.replace('Container', '') + 'Before');
            this.mode = 'horizontal';
            this.position = 0.5;
            this.fitMag = 1;
            this.mag = 1;
            this.tx = 0; this.ty = 0;
            this.isDragging = false;
            this.dragMode = null;
            this.rafId = null;
            this._initState();
            this._bindDrag();
            this._bindZoom();
            this._bindKeyboard();
            this._bindDoubleClick();
            this._bindToolbar();
            this._bindVideoLoad();
        }

        _initState() {
            this.container.classList.remove('vertical');
            this.afterEl.style.clipPath = 'inset(0 0 0 50%)';
            this._updateSliderUI(0.5);
        }

        _applyTransform() {
            const cw = this.container.offsetWidth, ch = this.container.offsetHeight;
            const vpW = this.viewport.clientWidth, vpH = this.viewport.clientHeight;
            const baseL = this.container.offsetLeft, baseT = this.container.offsetTop;
            const contentW = cw * this.mag, contentH = ch * this.mag;
            if (contentW <= vpW) this.tx = (vpW - contentW) / 2 - baseL;
            else this.tx = Math.min(0, Math.max(vpW - contentW - baseL, this.tx));
            if (contentH <= vpH) this.ty = (vpH - contentH) / 2 - baseT;
            else this.ty = Math.min(0, Math.max(vpH - contentH - baseT, this.ty));
            this.container.style.transform = 'translate(' + this.tx + 'px, ' + this.ty + 'px) scale(' + this.mag + ')';
        }

        _fit() { this.mag = this.fitMag; this.tx = 0; this.ty = 0; this._applyTransform(); }
        _oneToOne() { this.mag = this.oneToOneMag; this._applyTransform(); }
        _resetView() { this._fit(); this._updateSliderUI(0.5); }

        _applyMag(newMag, cx, cy) {
            const vp = this.viewport.getBoundingClientRect();
            const oldS = this.mag;
            if (cx === undefined) { cx = vp.left + vp.width / 2; cy = vp.top + vp.height / 2; }
            const px = (cx - vp.left - this.container.offsetLeft - this.tx) / oldS;
            const py = (cy - vp.top - this.container.offsetTop - this.ty) / oldS;
            this.mag = Math.min(8, Math.max(Math.min(this.fitMag * 0.4, 0.5), newMag));
            this.tx = (cx - vp.left) - px * this.mag - this.container.offsetLeft;
            this.ty = (cy - vp.top) - py * this.mag - this.container.offsetTop;
            this._applyTransform();
        }

        _updateSliderUI(pos) {
            this.position = Math.max(0, Math.min(1, pos));
            if (this.mode === 'horizontal') {
                const w = this.container.offsetWidth;
                this.slider.style.transform = 'translateX(' + (this.position * w) + 'px)';
                this.afterEl.style.clipPath = 'inset(0 0 0 ' + (this.position * 100) + '%)';
            } else {
                const h = this.container.offsetHeight;
                this.slider.style.transform = 'translateY(' + (this.position * h) + 'px)';
                this.afterEl.style.clipPath = 'inset(0 0 ' + (this.position * 100) + '% 0)';
            }
        }

        _setPositionFromEvent(clientX, clientY) {
            const rect = this.container.getBoundingClientRect();
            let pos = this.mode === 'horizontal' ? (clientX - rect.left) / Math.max(1, rect.width) : (clientY - rect.top) / Math.max(1, rect.height);
            if (Math.abs(pos - 0.5) < 0.03) pos = 0.5;
            this._updateSliderUI(pos);
        }

        _bindDrag() {
            const onStart = (clientX, clientY, mode) => {
                this.isDragging = true;
                this.dragMode = mode;
                this.container.classList.add('no-transition');
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
                            else { this.tx = startTx + (cx - clientX); this.ty = startTy + (cy - clientY); this._applyTransform(); }
                            this.rafId = null;
                        });
                    }
                };
                const onEnd = () => {
                    this.isDragging = false;
                    this.dragMode = null;
                    this.container.classList.remove('no-transition', 'panning');
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
            this.slider.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); onStart(e.clientX, e.clientY, 'div'); });
            this.slider.addEventListener('touchstart', (e) => { if (e.touches.length === 1) { e.stopPropagation(); onStart(e.touches[0].clientX, e.touches[0].clientY, 'div'); } }, { passive: true });
            this.container.addEventListener('mousedown', (e) => { if (e.button !== 0) return; e.preventDefault(); onStart(e.clientX, e.clientY, this.mag > this.fitMag * 1.02 ? 'pan' : 'div'); });
            this.container.addEventListener('touchstart', (e) => { if (e.touches.length === 1) onStart(e.touches[0].clientX, e.touches[0].clientY, this.mag > this.fitMag * 1.02 ? 'pan' : 'div'); }, { passive: true });
        }

        _bindZoom() {
            this.viewport.addEventListener('wheel', (e) => {
                e.preventDefault();
                this._applyMag(this.mag * (e.deltaY < 0 ? 1.18 : 1 / 1.18), e.clientX, e.clientY);
            }, { passive: false });
        }

        _bindKeyboard() {
            this.viewport.addEventListener('keydown', (e) => {
                switch (e.key) {
                    case 'ArrowLeft': e.preventDefault(); this.tx += 60; this._applyTransform(); break;
                    case 'ArrowRight': e.preventDefault(); this.tx -= 60; this._applyTransform(); break;
                    case 'ArrowUp': e.preventDefault(); this.ty += 60; this._applyTransform(); break;
                    case 'ArrowDown': e.preventDefault(); this.ty -= 60; this._applyTransform(); break;
                    case '+': case '=': e.preventDefault(); this._applyMag(this.mag * 1.18); break;
                    case '-': case '_': e.preventDefault(); this._applyMag(this.mag / 1.18); break;
                    case 'f': case 'F': e.preventDefault(); this._fit(); break;
                    case 'Home': e.preventDefault(); this._resetView(); break;
                    case '0': e.preventDefault(); this._oneToOne(); break;
                    case 'h': case 'H': e.preventDefault(); this.setMode('horizontal'); break;
                    case 'v': case 'V': e.preventDefault(); this.setMode('vertical'); break;
                    case ' ': e.preventDefault(); this._togglePlay(); break;
                }
            });
        }

        _bindDoubleClick() {
            this.viewport.addEventListener('dblclick', () => {
                if (this.mag > this.fitMag * 1.02) this._fit();
                else this._oneToOne();
            });
        }

        _bindToolbar() {
            const bind = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('click', fn); };
            bind('btnCompareHorizontal', () => this.setMode('horizontal'));
            bind('btnCompareVertical', () => this.setMode('vertical'));
            bind('btnCompareZoomIn', () => this._applyMag(this.mag * 1.18));
            bind('btnCompareZoomOut', () => this._applyMag(this.mag / 1.18));
            bind('btnCompareFit', () => this._fit());
            bind('btnCompareReset', () => this._resetView());
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
                if (icon) icon.className = 'bi bi-arrows-expand-vertical';
            } else {
                this.container.classList.remove('vertical');
                const icon = this.slider.querySelector('i');
                if (icon) icon.className = 'bi bi-arrows-expand-horizontal';
            }
            this._updateSliderUI(this.position);
        }

        _bindVideoLoad() {
            const tryAlign = () => {
                if (!this.beforeVideo || this.beforeVideo.readyState < 2) return;
                const ratio = this.beforeVideo.videoWidth / this.beforeVideo.videoHeight;
                if (!ratio || !isFinite(ratio)) return;
                const vpRect = this.viewport.getBoundingClientRect();
                const maxW = Math.max(200, vpRect.width - 8);
                const maxH = Math.max(200, vpRect.height - 8);
                let w = maxW, h = w / ratio;
                if (h > maxH) { h = maxH; w = h * ratio; }
                this.container.style.aspectRatio = ratio;
                this.container.style.width = w + 'px';
                this.container.classList.add('is-aligned');
                this.fitMag = 1;
                this.oneToOneMag = Math.max(1, this.beforeVideo.videoWidth / w);
                this._fit();
                requestAnimationFrame(() => { this._updateSliderUI(this.position); this._applyTransform(); });
            };
            if (this.beforeVideo) {
                this.beforeVideo.onloadedmetadata = tryAlign;
                this.beforeVideo.onerror = () => console.error('视频加载失败');
            }
        }

        _togglePlay() {
            if (this.beforeVideo) {
                const afterVideo = document.getElementById(this.container.id.replace('Container', '') + 'AfterImg');
                if (this.beforeVideo.paused) { this.beforeVideo.play(); if (afterVideo) afterVideo.play(); }
                else { this.beforeVideo.pause(); if (afterVideo) afterVideo.pause(); }
            }
        }

        destroy() {
            if (this.dragAbort) this.dragAbort.abort();
            if (this.rafId) cancelAnimationFrame(this.rafId);
        }
    }
})();
