# PDF 工具箱 — 设计文档

## 概述

在 PDF Manager 现有单页应用基础上，集成 PDF 工具箱功能。用户可以在翻译工作流页面直接使用 PDF 工具（合并、拆分、压缩、水印等），无需切换页面。

## UI 设计

### 页面布局

主页面（index.html）下方新增一个「PDF 工具箱」区域，位于上传工作流配置与最近任务列表之间：

```
[PDF Manager Logo]       [设置] [关于]
─────────────────────────────────────────────────
  工作流配置 [book] [translate] [render]
  ┌──────────────────────────────────────┐
  │  上传区域 + 提交翻译按钮             │
  └──────────────────────────────────────┘
  ┌──────────────────────────────────────┐
  │  📦 PDF 工具箱                       │
  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
  │  │合并  │ │拆分  │ │压缩  │ │旋转  │ │
  │  └──────┘ └──────┘ └──────┘ └──────┘ │
  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
  │  │水印  │ │页码  │ │裁剪  │ │加密  │ │
  │  └──────┘ └──────┘ └──────┘ └──────┘ │
  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
  │  │元数据│ │重排  │ │→图片 │ │更多▼ │ │
  │  └──────┘ └──────┘ └──────┘ └──────┘ │
  └──────────────────────────────────────┘
  最近任务列表
```

### 交互模式

点击工具图标 → 在当前页面弹出 Slide-over 侧边面板。面板包含：
- 标题 + 关闭按钮
- 文件上传/选择区域（可重用现有 upload 逻辑）
- 工具特定配置项（如合并的拖拽排序、旋转的角度选择）
- 操作按钮（执行 / 下载）

### 技术实现

**前端**：
- 新模块 `frontend/src/js/features/pdf-tools/controller.js` — 工具箱主控制器
- 新模块 `frontend/src/js/features/pdf-tools/` — 各工具面板
- 新模块 `frontend/src/js/pdf-tools-api.js` — API 调用封装
- 复用现有 dialog/modal 组件

**后端 Rust API**：
- 新路由模块 `backend/rust_api/src/routes/pdf_tools.rs`
- 路由注册到 `mod.rs`
- 每个工具一个 POST 端点

**后端 Python**：
- 新模块 `backend/scripts/services/pdf_tools/` — PDF 工具处理
- 每个功能一个子模块，复用现有 PyMuPDF / pikepdf 逻辑

### 分批实现策略

#### 第一批：核心工具（6 个）

| 功能 | 后端实现 | Rust API | 前端 |
|------|---------|----------|------|
| **合并 PDF** | 新建 `pdf_tools/merger.py` — pikepdf 逐页拼接 | `POST /api/v1/pdf-tools/merge` | 多文件上传 + 拖拽排序 + 下载 |
| **拆分 PDF** | 复用 `extract_pages_with_pikepdf()` | `POST /api/v1/pdf-tools/split` | 文件上传 + 页码范围输入 |
| **压缩 PDF** | 复用 `compress_pdf_images_only_impl()` | `POST /api/v1/pdf-tools/compress` | 文件上传 + DPI 选择 + 大小预览 |
| **旋转 PDF** | PyMuPDF `page.set_rotation()` | `POST /api/v1/pdf-tools/rotate` | 文件上传 + 角度选择 + 范围选择 |
| **元数据编辑** | PyMuPDF `pdf.metadata` dict | `PUT /api/v1/pdf-tools/metadata` | 表单编辑 + 预览 |
| **加密/解密** | PyMuPDF `pdf.save(encryption=...)` | `POST /api/v1/pdf-tools/encrypt` /decrypt | 密码输入 + 权限设置 |

#### 第二批：常用工具（5 个）

| 功能 | 后端实现 | Rust API | 前端 |
|------|---------|----------|------|
| **水印** | 复用 `overlay_pdf_pages_with_pikepdf()` | `POST /api/v1/pdf-tools/watermark` | 文本/图片水印配置 |
| **页码** | PyMuPDF `page.insert_text()` | `POST /api/v1/pdf-tools/page-numbers` | 位置/格式/起始页配置 |
| **裁剪** | PyMuPDF `page.set_cropbox()` | `POST /api/v1/pdf-tools/crop` | 预设 + 自定义裁剪 |
| **页面重排** | pikepdf page reorder | `POST /api/v1/pdf-tools/reorder` | 拖拽缩略图排序 |
| **PDF→图片** | PyMuPDF `page.get_pixmap()` | `POST /api/v1/pdf-tools/to-images` | 范围/DPI/格式选择 |

#### 第三批：高级功能（5 个）

| 功能 | 后端实现 | Rust API | 前端 |
|------|---------|----------|------|
| **签名** | PyMuPDF insert image | `POST /api/v1/pdf-tools/sign` | 签名绘制 + 定位 |
| **注释** | PyMuPDF annotation API | `POST /api/v1/pdf-tools/annotations` | 高亮/批注 |
| **PDF 比较** | PyMuPDF text diff + pixmap diff | `POST /api/v1/pdf-tools/diff` | 对比视图 |
| **图片→PDF** | PyMuPDF new page + insert_image | `POST /api/v1/pdf-tools/pdf-from-images` | 图片上传 |
| **批量处理** | 编排器 + 任务队列 | `POST /api/v1/pdf-tools/batch` | 操作编排 UI |

## API 设计

所有工具使用统一前缀 `/api/v1/pdf-tools/`，POST 请求，multipart/form-data 上传文件，返回 JSON 包含下载链接。

```json
// POST /api/v1/pdf-tools/merge 请求示例
{
  "files": ["upload_id_1", "upload_id_2", "upload_id_3"],
  "file_names": ["chapter1.pdf", "chapter2.pdf", "chapter3.pdf"]
}

// 响应
{
  "code": 0,
  "data": {
    "download_url": "/api/v1/pdf-tools/result/abc123",
    "file_name": "merged.pdf",
    "file_size": 2048576,
    "page_count": 42
  }
}
```

工具结果文件保留 1 小时后自动清理。

## 错误处理

- 文件损坏/加密：返回 400 + 明确错误信息
- 文件过大（超过 upload_max_bytes）：返回 413
- 处理超时（超过 300s）：返回 408
- 不支持的页面尺寸组合（merge）：自动适应，不报错
- 无效页码范围（split）：返回 400

## 测试

- 每个工具至少一个成功路径测试
- 边界条件：空文件、单页 PDF、超大 PDF、加密 PDF
- 前端：smoke test 验证工具箱渲染和交互
