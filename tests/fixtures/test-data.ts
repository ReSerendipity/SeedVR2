/**
 * Test data factory for SeedVR2 WebUI E2E tests.
 *
 * Provides:
 * - Video file paths and mock data
 * - Image file paths and mock data
 * - Form parameter presets (default, high-res, low-vram)
 * - Mock API response generators for all endpoints
 *
 * All data is designed to be used with Playwright route mocking
 * and form filling operations.
 */

// ============================================================
// Video test data
// ============================================================

/** Sample video file paths for upload testing */
export const VIDEO_FILES = {
  /** Small test video suitable for fast test runs */
  small: 'test-assets/videos/sample.mp4',
  /** Medium resolution video for standard testing */
  medium: 'test-assets/videos/sample.mp4',
  /** High resolution video for quality-related tests */
  large: 'test-assets/videos/sample.mp4',
  /** Corrupted video file for error handling tests */
  corrupted: 'test-assets/videos/sample.mp4',
  /** Unsupported format for validation tests */
  unsupported: 'test-assets/videos/sample.mp4',
} as const;

/** Mock video metadata returned by the backend */
export const MOCK_VIDEO_META = {
  small: {
    filename: 'sample_720p_5s.mp4',
    width: 1280,
    height: 720,
    fps: 30,
    duration: 5.0,
    size: 5242880,
    codec: 'h264',
  },
  medium: {
    filename: 'sample_1080p_10s.mp4',
    width: 1920,
    height: 1080,
    fps: 30,
    duration: 10.0,
    size: 15728640,
    codec: 'h264',
  },
  large: {
    filename: 'sample_4k_30s.mp4',
    width: 3840,
    height: 2160,
    fps: 30,
    duration: 30.0,
    size: 104857600,
    codec: 'h265',
  },
} as const;

// ============================================================
// Image test data
// ============================================================

/** Sample image file paths for upload testing */
export const IMAGE_FILES = {
  /** Standard JPEG image */
  jpeg: 'test-assets/images/sample.jpg',
  /** PNG image with transparency */
  png: 'test-assets/images/sample.png',
  /** WebP format image */
  webp: 'test-assets/images/sample.jpg',
  /** Corrupted image for error handling tests */
  corrupted: 'test-assets/images/sample.jpg',
  /** Unsupported format for validation tests */
  unsupported: 'test-assets/images/sample.jpg',
} as const;

/** Mock image metadata returned by the backend */
export const MOCK_IMAGE_META = {
  jpeg: {
    filename: 'sample.jpg',
    width: 1920,
    height: 1080,
    size: 524288,
    format: 'jpeg',
  },
  png: {
    filename: 'sample.png',
    width: 1920,
    height: 1080,
    size: 1048576,
    format: 'png',
  },
  webp: {
    filename: 'sample.webp',
    width: 1920,
    height: 1080,
    size: 262144,
    format: 'webp',
  },
} as const;

// ============================================================
// Form parameter presets
// ============================================================

/**
 * Form parameter presets for video/image restore operations.
 * These match the form fields in the WebUI.
 */
export const FORM_PRESETS = {
  /** Default settings - balanced quality and speed */
  default: {
    model: 'seedvr2_ema_7b_fp16',
    resolution: 'auto',
    seed: -1,
    denoiseStrength: 0.5,
    cfgScale: 7.0,
    samplingSteps: 20,
    batchSize: 1,
    fp8Enabled: false,
    blockSwapEnabled: false,
  },
  /** High resolution preset - maximum quality */
  highRes: {
    model: 'seedvr2_ema_7b_sharp_fp16',
    resolution: '4k',
    seed: 42,
    denoiseStrength: 0.7,
    cfgScale: 9.0,
    samplingSteps: 50,
    batchSize: 1,
    fp8Enabled: false,
    blockSwapEnabled: false,
  },
  /** Low VRAM preset - optimized for limited GPU memory */
  lowVram: {
    model: 'seedvr2_ema_3b_fp16',
    resolution: '720p',
    seed: -1,
    denoiseStrength: 0.5,
    cfgScale: 7.0,
    samplingSteps: 15,
    batchSize: 1,
    fp8Enabled: true,
    blockSwapEnabled: true,
  },
} as const;

export type FormPresetName = keyof typeof FORM_PRESETS;

// ============================================================
// Mock API response generators
// ============================================================

/**
 * Generate a mock health check response.
 */
export function mockHealthResponse(overrides?: Partial<HealthResponse>): HealthResponse {
  return {
    status: 'ok',
    uptime_seconds: 3600,
    system: {
      platform: 'Windows-10-10.0.19045-SP0',
      python_version: '3.12.1',
      cpu_count: 16,
      memory_total_gb: 32.0,
      memory_available_gb: 24.0,
      memory_utilization_pct: 25.0,
    },
    model: {
      model_loaded: true,
      current_model_size: '7b',
      current_precision: 'fp16',
      model_info: {},
      available_models: ['3b', '7b'],
    },
    gpu: {
      backend: 'cuda',
      device_name: 'NVIDIA GeForce RTX 4090',
      is_gpu_available: true,
    },
    ...overrides,
  };
}

/**
 * Generate a mock GPU info response.
 */
export function mockGpuResponse(overrides?: Partial<GpuResponse>): GpuResponse {
  return {
    backend: 'cuda',
    device_name: 'NVIDIA GeForce RTX 4090',
    vram_total_mb: 24576,       // 24 GB
    vram_available_mb: 20480,   // 20 GB
    utilization_pct: 16.67,
    cuda_version: '12.4',
    driver_version: '550.54.15',
    memory: {
      total_mb: 24576,
      allocated_mb: 4096,
      reserved_mb: 4096,
      available_mb: 20480,
      utilization_pct: 16.67,
    },
    ...overrides,
  };
}

/**
 * Generate a mock system info response.
 */
export function mockSystemResponse(overrides?: Partial<SystemResponse>): SystemResponse {
  return {
    os: 'Windows',
    os_version: '10.0.19045',
    processor: 'AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD',
    python_version: '3.12.1',
    gpu: {
      total_mb: 24576,
      allocated_mb: 4096,
      reserved_mb: 4096,
      available_mb: 20480,
      utilization_pct: 16.67,
    },
    memory: {
      total_mb: 32768,
      available_mb: 24576,
      used_mb: 8192,
      utilization_pct: 25.0,
    },
    ...overrides,
  };
}

/**
 * Generate a mock settings response.
 */
export function mockSettingsResponse(overrides?: Partial<SettingsResponse>): SettingsResponse {
  return {
    model: {
      name: 'seedvr2_ema_7b_fp16',
      auto_load: true,
    },
    server: {
      host: '127.0.0.1',
      port: 7870,
      auto_open_browser: true,
    },
    restore: {
      default_resolution: 'auto',
      default_denoise_strength: 0.5,
      default_cfg_scale: 7.0,
      default_sampling_steps: 20,
    },
    advanced: {
      fp8_enabled: false,
      block_swap_enabled: false,
      max_batch_size: 1,
    },
    locale: 'zh',
    ...overrides,
  };
}

/**
 * Generate a mock model status response.
 * The page JS reads `available_models` from this endpoint.
 */
export function mockModelStatusResponse(
  state: 'loaded' | 'loading' | 'unloaded' | 'error' = 'loaded',
  overrides?: Partial<ModelStatusResponse>,
): ModelStatusResponse {
  return {
    state,
    model_name: state === 'loaded' ? 'seedvr2_ema_7b_fp16' : undefined,
    progress: state === 'loading' ? 0.5 : undefined,
    error: state === 'error' ? 'Failed to load model' : undefined,
    vram_usage: state === 'loaded' ? 8589934592 : 0,
    available_models: state === 'loaded' ? ['3B', '7B'] : [],
    ...overrides,
  };
}

/**
 * Generate a mock video restore task response.
 */
export function mockVideoRestoreResponse(
  taskId = 'test-task-001',
  overrides?: Partial<VideoRestoreResponse>,
): VideoRestoreResponse {
  return {
    task_id: taskId,
    status: 'processing',
    message: 'Video restore task created',
    ...overrides,
  };
}

/**
 * Generate a mock video progress SSE payload.
 * Progress is in percentage (0-100) to match the frontend JS expectations.
 */
export function mockVideoProgressPayload(
  taskId = 'test-task-001',
  progress = 50,
  overrides?: Partial<VideoProgressPayload>,
): VideoProgressPayload {
  const totalFrames = overrides?.total_frames ?? 150;
  const currentFrame = overrides?.current_frame ?? Math.floor((progress / 100) * totalFrames);
  return {
    task_id: taskId,
    progress,
    current_frame: currentFrame,
    total_frames: totalFrames,
    current_step: Math.floor((progress / 100) * 20),
    total_steps: 20,
    status: progress >= 100 ? 'completed' : 'processing',
    message: `Processing frame ${Math.floor(progress)}%`,
    ...overrides,
  };
}

/**
 * Generate a mock video result response.
 */
export function mockVideoResultResponse(
  taskId = 'test-task-001',
  overrides?: Partial<VideoResultResponse>,
): VideoResultResponse {
  return {
    task_id: taskId,
    status: 'completed',
    output_path: `outputs/video/${taskId}/restored.mp4`,
    output_url: `/api/restore/video/${taskId}/download`,
    original_filename: 'sample_720p_5s.mp4',
    output_filename: 'restored.mp4',
    processing_time: 45.2,
    ...overrides,
  };
}

/**
 * Generate a mock image restore task response.
 */
export function mockImageRestoreResponse(
  taskId = 'test-img-001',
  overrides?: Partial<ImageRestoreResponse>,
): ImageRestoreResponse {
  return {
    task_id: taskId,
    status: 'processing',
    message: 'Image restore task created',
    ...overrides,
  };
}

/**
 * Generate a mock image result response.
 */
export function mockImageResultResponse(
  taskId = 'test-img-001',
  overrides?: Partial<ImageResultResponse>,
): ImageResultResponse {
  return {
    task_id: taskId,
    status: 'completed',
    output_path: `outputs/image/${taskId}/restored.png`,
    output_url: `/api/restore/image/${taskId}/download`,
    original_filename: 'sample.jpg',
    output_filename: 'restored.png',
    processing_time: 5.3,
    ...overrides,
  };
}

/**
 * Generate a mock history list response with pagination.
 */
export function mockHistoryResponse(
  overrides?: Partial<HistoryListResponse>,
): HistoryListResponse {
  const items: HistoryItem[] = [
    {
      id: 1,
      task_type: 'video',
      input_file: 'C:\\Videos\\sample_720p_5s.mp4',
      output_file: 'outputs\\video\\1\\restored.mp4',
      model_size: '7b',
      status: 'completed',
      parameters: '{}',
      processing_time: 45.2,
      created_at: '2025-01-15T10:30:00Z',
      error_message: '',
    },
    {
      id: 2,
      task_type: 'image',
      input_file: 'C:\\Images\\sample.jpg',
      output_file: 'outputs\\image\\2\\restored.png',
      model_size: '7b',
      status: 'completed',
      parameters: '{}',
      processing_time: 5.3,
      created_at: '2025-01-15T11:00:00Z',
      error_message: '',
    },
    {
      id: 3,
      task_type: 'video',
      input_file: 'C:\\Videos\\corrupted.mp4',
      output_file: '',
      model_size: '3b',
      status: 'failed',
      parameters: '{}',
      processing_time: 0,
      created_at: '2025-01-15T11:30:00Z',
      error_message: 'File is corrupted or unsupported',
    },
  ];

  return {
    records: items,
    total: items.length,
    page: 1,
    page_size: 20,
    total_pages: 1,
    ...overrides,
  };
}

/**
 * Generate a mock history statistics response.
 */
export function mockHistoryStatsResponse(overrides?: Partial<HistoryStatsResponse>): HistoryStatsResponse {
  return {
    total_tasks: 150,
    completed_tasks: 130,
    failed_tasks: 15,
    cancelled_tasks: 5,
    video_tasks: 100,
    image_tasks: 50,
    total_processing_time: 7200.5,
    avg_processing_time: 48.0,
    ...overrides,
  };
}

/**
 * Generate a mock batch video restore response.
 */
export function mockBatchVideoResponse(overrides?: Partial<BatchResponse>): BatchResponse {
  return {
    batch_id: 'batch-vid-001',
    task_ids: ['task-001', 'task-002', 'task-003'],
    total: 3,
    status: 'processing',
    ...overrides,
  };
}

/**
 * Generate a mock batch image restore response.
 */
export function mockBatchImageResponse(overrides?: Partial<BatchResponse>): BatchResponse {
  return {
    batch_id: 'batch-img-001',
    task_ids: ['task-001', 'task-002'],
    total: 2,
    status: 'processing',
    ...overrides,
  };
}

/**
 * Generate a mock batch progress response.
 * The page JS expects: { results, current_index, completed, failed, total, status }
 * Each result item has: { name, path, status, progress, retry_count?, error? }
 */
export function mockBatchProgressResponse(overrides?: Partial<BatchProgressResponse>): BatchProgressResponse {
  return {
    batch_id: 'batch-001',
    total: 3,
    completed: 1,
    failed: 0,
    processing: 2,
    progress: 0.33,
    current_index: 1,
    status: 'processing',
    results: [
      { name: 'video1.mp4', path: 'C:\\Videos\\video1.mp4', status: 'completed', progress: 1.0, retry_count: 0 },
      { name: 'video2.mp4', path: 'C:\\Videos\\video2.mp4', status: 'processing', progress: 0.5, retry_count: 0 },
      { name: 'video3.mp4', path: 'C:\\Videos\\video3.mp4', status: 'pending', progress: 0.0, retry_count: 0 },
    ],
    ...overrides,
  };
}

/**
 * Generate a mock locales list response.
 */
export function mockLocalesResponse(): LocaleResponse[] {
  return [
    { code: 'zh', name: '中文' },
    { code: 'en', name: 'English' },
    { code: 'ja', name: '日本語' },
    { code: 'fr', name: 'Français' },
  ];
}

/**
 * Generate a mock browse directory response.
 * The page JS expects: { current_path, parent_path, items: [{ name, path, type }] }
 */
export function mockBrowseDirResponse(overrides?: Partial<BrowseDirResponse>): BrowseDirResponse {
  return {
    current_path: 'C:\\Users\\test\\Videos',
    parent_path: 'C:\\Users\\test',
    items: [
      { name: 'sample.mp4', path: 'C:\\Users\\test\\Videos\\sample.mp4', type: 'file' },
      { name: 'Subfolder', path: 'C:\\Users\\test\\Videos\\Subfolder', type: 'folder' },
    ],
    ...overrides,
  };
}

/**
 * Generate a mock scan folder response for image restore.
 */
export function mockScanFolderResponse(overrides?: Partial<ScanFolderResponse>): ScanFolderResponse {
  return {
    path: 'C:\\Users\\test\\Images',
    images: [
      { name: 'photo1.jpg', path: 'C:\\Users\\test\\Images\\photo1.jpg', size: 524288 },
      { name: 'photo2.png', path: 'C:\\Users\\test\\Images\\photo2.png', size: 1048576 },
    ],
    total: 2,
    ...overrides,
  };
}

// ============================================================
// Type definitions for mock responses
// ============================================================

export interface HealthResponse {
  status: string;
  uptime_seconds: number;
  system: {
    platform: string;
    python_version: string;
    cpu_count: number;
    memory_total_gb: number;
    memory_available_gb: number;
    memory_utilization_pct: number;
  };
  model: {
    model_loaded: boolean;
    current_model_size?: string;
    current_precision?: string;
    model_info?: Record<string, unknown>;
    available_models?: string[];
  };
  gpu: {
    backend: string;
    device_name: string;
    is_gpu_available: boolean;
  };
}

export interface GpuResponse {
  backend: string;
  device_name: string;
  vram_total_mb: number;
  vram_available_mb: number;
  utilization_pct: number;
  cuda_version: string;
  driver_version: string;
  memory: {
    total_mb: number;
    allocated_mb: number;
    reserved_mb: number;
    available_mb: number;
    utilization_pct: number;
  };
}

export interface SystemResponse {
  os: string;
  os_version: string;
  processor: string;
  python_version: string;
  gpu: {
    total_mb: number;
    allocated_mb: number;
    reserved_mb: number;
    available_mb: number;
    utilization_pct: number;
  };
  memory: {
    total_mb: number;
    available_mb: number;
    used_mb: number;
    utilization_pct: number;
  };
}

export interface SettingsResponse {
  model: {
    name: string;
    auto_load: boolean;
  };
  server: {
    host: string;
    port: number;
    auto_open_browser: boolean;
  };
  restore: {
    default_resolution: string;
    default_denoise_strength: number;
    default_cfg_scale: number;
    default_sampling_steps: number;
  };
  advanced: {
    fp8_enabled: boolean;
    block_swap_enabled: boolean;
    max_batch_size: number;
  };
  locale: string;
}

export interface ModelStatusResponse {
  state: 'loaded' | 'loading' | 'unloaded' | 'error';
  model_name?: string;
  progress?: number;
  error?: string;
  vram_usage: number;
  available_models?: string[];
}

export interface VideoRestoreResponse {
  task_id: string;
  status: string;
  message: string;
}

export interface VideoProgressPayload {
  task_id: string;
  progress: number;
  current_frame: number;
  total_frames: number;
  current_step: number;
  total_steps: number;
  status: string;
  message: string;
}

export interface VideoResultResponse {
  task_id: string;
  status: string;
  output_path: string;
  output_url: string;
  original_filename: string;
  output_filename: string;
  processing_time: number;
}

export interface ImageRestoreResponse {
  task_id: string;
  status: string;
  message: string;
}

export interface ImageResultResponse {
  task_id: string;
  status: string;
  output_path: string;
  output_url: string;
  original_filename: string;
  output_filename: string;
  processing_time: number;
}

export interface HistoryItem {
  id: number;
  task_type: 'video' | 'image';
  input_file: string;
  output_file: string;
  model_size: string;
  status: 'completed' | 'failed' | 'cancelled' | 'processing' | 'pending';
  parameters: string;
  processing_time: number;
  created_at: string;
  error_message: string;
}

export interface HistoryListResponse {
  records: HistoryItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface HistoryStatsResponse {
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  cancelled_tasks: number;
  video_tasks: number;
  image_tasks: number;
  total_processing_time: number;
  avg_processing_time: number;
}

export interface BatchResponse {
  batch_id: string;
  task_ids: string[];
  total: number;
  status: string;
}

export interface BatchTaskProgress {
  name: string;
  path?: string;
  status: string;
  progress: number;
  retry_count?: number;
  error?: string;
}

export interface BatchProgressResponse {
  batch_id: string;
  total: number;
  completed: number;
  failed: number;
  processing: number;
  progress: number;
  current_index?: number;
  status?: string;
  results: BatchTaskProgress[];
}

export interface LocaleResponse {
  code: string;
  name: string;
}

export interface BrowseDirResponse {
  current_path: string;
  parent_path?: string;
  items: Array<{
    name: string;
    path: string;
    type: 'file' | 'folder' | 'drive';
  }>;
}

export interface ScanFolderResponse {
  path: string;
  images: Array<{
    name: string;
    path: string;
    size: number;
  }>;
  total: number;
}
