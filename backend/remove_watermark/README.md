# 🎨 水印去除模块

基于 YOLO11x + LaMa 的智能水印检测与去除系统。

> **⚠️ 实验性功能**：本模块目前为实验性功能，效果取决于水印类型和图片质量。

## 📋 目录

- [技术方案](#-技术方案)
- [快速开始](#-快速开始)
- [效果优化指南](#-效果优化指南)
- [支持的格式](#-支持的格式)
- [API 使用](#-api-使用)
- [常见问题](#-常见问题)

---

## 🔧 技术方案

### 核心技术栈

```
图片水印去除流程：
输入图片
  ↓
YOLO11x 检测水印位置（专用模型）
  ↓
生成水印掩码 + 膨胀处理
  ↓
LaMa 深度学习修复（或 OpenCV 降级）
  ↓
输出干净图片

PDF 处理流程：
输入 PDF
  ↓
自动检测类型
  ↓
  ├─ 可编辑 PDF → PyMuPDF 删除水印对象
  └─ 扫描件 PDF → 转图片 → 去水印 → 重组 PDF
```

### 关键组件

| 组件 | 说明 | 优势 |
|------|------|------|
| **YOLO11x** | 在水印数据集上训练的专用检测模型 | 高精度检测水印位置和边界 |
| **LaMa** | Large Mask Inpainting 深度学习修复模型 | 自然填充大面积水印区域 |
| **PyMuPDF** | PDF 处理库 | 可编辑 PDF 的水印对象删除 |
| **OpenCV** | 计算机视觉库 | 降级方案（LaMa 不可用时） |

---

## 🚀 快速开始

### 1. 安装依赖

所有依赖已集成到主项目：

```bash
cd backend
pip install -r requirements.txt
```

### 2. 通过 Web 界面使用

1. 启动服务（参考主项目 README）
2. 打开 Web 界面，提交任务
3. 在提交表单中勾选 **"启用水印去除"**
4. 可选：调整检测参数

### 3. 首次运行

首次运行会自动从 HuggingFace 下载 YOLO11x 模型（约 200MB），请确保网络连接。

模型缓存位置：`~/.cache/watermark_models/`

---

## 💡 效果优化指南

### 哪些水印效果好？

✅ **推荐使用场景**：

- 常规的文字/Logo 水印（如 "版权所有"、公司 Logo）
- 位置固定、对比度适中的水印
- 水印与背景有明显区分
- 图片质量较好，分辨率适中

❌ **效果可能不佳**：

- 大面积背景水印（覆盖整个图片）
- 半透明、低对比度的水印
- 与内容深度融合的艺术水印
- 极低分辨率或严重失真的图片

### 参数调优建议

#### 1. **检测置信度（Confidence Threshold）**

**默认值：0.35**

- **调低（0.2-0.3）**：
  - ✅ 适合：水印不明显、半透明、对比度低
  - ⚠️ 风险：可能误检正常内容

- **调高（0.4-0.5）**：
  - ✅ 适合：水印明显、想避免误检
  - ⚠️ 风险：可能漏检部分水印

#### 2. **去除范围扩展（Dilation）**

**默认值：10 像素**

- **调小（0-5）**：
  - ✅ 适合：精确的水印边界、担心影响周围内容
  - ⚠️ 风险：水印边缘可能有残留

- **调大（15-30）**：
  - ✅ 适合：水印边缘模糊、有残影
  - ⚠️ 风险：可能去除过多正常内容

### 实战案例

#### 案例 1：清晰 Logo 水印

```yaml
场景: 图片角落有公司 Logo
推荐参数:
  - 置信度: 0.35（默认）
  - 膨胀: 10（默认）
效果: ⭐⭐⭐⭐⭐
```

#### 案例 2：半透明文字水印

```yaml
场景: 图片中央有半透明 "Sample" 文字
推荐参数:
  - 置信度: 0.25（降低）
  - 膨胀: 15（增加）
效果: ⭐⭐⭐⭐
```

#### 案例 3：大面积背景水印

```yaml
场景: 整个图片被斜铺的重复水印覆盖
推荐参数:
  - 置信度: 0.3
  - 膨胀: 20
效果: ⭐⭐⭐（取决于水印复杂度）
注意: 这类水印效果最不稳定
```

### 如何获得更好的效果？

#### 选项 1：使用自定义 YOLO 模型（推荐）

如果默认模型效果不佳，可以训练自己的 YOLO 模型：

1. **收集数据**：准备训练数据集
   - 数据量取决于水印类型的复杂度和多样性
   - 建议参考 Ultralytics YOLO 官方文档的数据集要求
   - 数据应覆盖不同场景、角度、光照条件以提高泛化能力

2. **标注水印**：使用 LabelImg、Roboflow 等工具标注水印位置
   - 标注边界框应准确贴合水印区域
   - 按照 YOLO 格式准备数据集（训练集/验证集/测试集）

3. **训练模型**：使用 Ultralytics YOLO 框架训练
   - 建议从预训练权重（如 yolo11x.pt）开始微调
   - 根据验证集表现调整训练参数
   - 详细教程参考：<https://docs.ultralytics.com/>

4. **替换模型**：将训练好的模型替换到缓存目录

```python
from watermark_remover import WatermarkRemover

# 使用自定义模型
remover = WatermarkRemover(
    model_path="/path/to/your/custom_model.pt",
    device="cuda",
    use_lama=True
)
```

#### 选项 2：批量测试找最佳参数

```python
import itertools

# 参数组合
confidences = [0.25, 0.30, 0.35, 0.40]
dilations = [5, 10, 15, 20]

# 批量测试
for conf, dil in itertools.product(confidences, dilations):
    result = remover.remove_watermark(
        image_path="test.jpg",
        output_path=f"result_c{conf}_d{dil}.jpg",
        conf_threshold=conf,
        dilation=dil
    )
```

#### 选项 3：检查调试文件

每次处理都会自动保存调试文件：

```
watermark_removed/
├── detection_*.jpg  # 查看检测框是否准确
├── mask_*.jpg       # 查看掩码范围是否合适
└── clean_*.jpg      # 最终结果
```

**调试步骤**：

1. 查看 `detection_*.jpg`，检查是否检测到所有水印
2. 如果漏检 → 降低置信度
3. 如果误检 → 提高置信度
4. 查看 `mask_*.jpg`，检查去除范围是否合适
5. 如果有残留 → 增加膨胀值
6. 如果去除过多 → 减少膨胀值

---

## 📄 支持的格式

### 图片格式

| 格式 | 支持 | 说明 |
|------|------|------|
| PNG | ✅ | 推荐，无损格式 |
| JPG/JPEG | ✅ | 常用格式 |
| BMP | ✅ | 位图格式 |
| TIFF | ✅ | 高质量格式 |
| WebP | ✅ | 现代格式 |

### PDF 格式

| 类型 | 处理方式 | 效果 |
|------|---------|------|
| 可编辑 PDF | PyMuPDF 删除水印对象 | ⭐⭐⭐⭐ |
| 扫描件 PDF | 转图片 → 去水印 → 重组 | ⭐⭐⭐ |

---

## 🔌 API 使用

### Python API

```python
from remove_watermark import WatermarkRemover

# 初始化
remover = WatermarkRemover(
    device="cuda",        # 使用 GPU（或 "cpu"）
    use_lama=True        # 使用 LaMa 修复
)

# 去除图片水印
result = remover.remove_watermark(
    image_path="input.png",
    output_path="output.png",
    conf_threshold=0.35,  # 检测置信度
    dilation=10          # 掩码膨胀
)

# 清理资源
remover.cleanup()
```

### REST API

通过主项目的 Web API 使用：

```bash
curl -X POST http://localhost:8000/api/v1/tasks/submit \
  -F 'file=@image.png' \
  -F 'backend=pipeline' \
  -F 'remove_watermark=true' \
  -F 'watermark_conf_threshold=0.35' \
  -F 'watermark_dilation=10'
```

---

## ❓ 常见问题

### Q1: 为什么检测不到水印？

**可能原因**：

1. 置信度阈值太高 → 降低到 0.25-0.30
2. 水印类型不在训练数据中 → 考虑训练自定义模型
3. 水印太模糊或透明 → 检查原图质量

**解决方法**：查看 `detection_*.jpg` 文件，确认是否有检测框

### Q2: 为什么去除后有残留？

**可能原因**：

1. 膨胀值太小 → 增加到 15-20
2. 水印边缘模糊 → 增加膨胀值
3. 复杂水印 → 可能需要多次处理

**解决方法**：查看 `mask_*.jpg` 文件，确认掩码是否覆盖完整

### Q3: 为什么把正常内容也去除了？

**可能原因**：

1. 置信度太低导致误检 → 提高到 0.4-0.5
2. 膨胀值太大 → 减少到 5-10
3. 正常内容与水印相似 → 需要更精确的模型

**解决方法**：查看 `detection_*.jpg` 和 `mask_*.jpg` 调整参数

### Q4: 首次运行很慢？

**原因**：首次运行需要下载 YOLO11x 模型（约 200MB）

**解决**：

- 确保网络连接正常
- 国内用户可能需要配置代理
- 模型会缓存到本地，后续运行秒启动

### Q5: GPU 内存不足？

**解决方法**：

```python
# 使用 CPU
remover = WatermarkRemover(device="cpu", use_lama=True)

# 或者不使用 LaMa（更省内存）
remover = WatermarkRemover(device="cuda", use_lama=False)
```

### Q6: 大面积背景水印效果不好？

**说明**：大面积背景水印是最难处理的类型，因为：

- 水印覆盖范围广，修复区域大
- 容易破坏原图结构
- YOLO 可能检测不全

**建议**：

- 这种情况下，传统图像处理方法可能效果更好
- 考虑使用其他专门的工具
- 或接受部分残留，后续人工处理

---

## 📚 技术参考

- **YOLO11x**: [Ultralytics YOLO](https://github.com/ultralytics/ultralytics)
- **LaMa**: [Resolution-robust Large Mask Inpainting](https://arxiv.org/abs/2109.07161)
- **PyMuPDF**: [PDF Processing Library](https://pymupdf.readthedocs.io/)

---

## 🎯 总结

### ✅ 优势

- 自动检测，无需手动标注水印位置
- 深度学习修复，效果自然
- 支持图片和 PDF 多种格式
- GPU 加速，处理速度快
- 参数可调，适应不同场景

### ⚠️ 局限

- 效果依赖水印类型和图片质量
- 大面积背景水印效果有限
- 首次运行需要下载模型
- 某些特殊水印可能需要自定义模型

### 🚀 最佳实践

1. **先测试**：在小范围样本上测试效果
2. **调参数**：根据检测可视化调整参数
3. **查调试**：利用调试文件分析问题
4. **训练模型**：效果不佳时考虑自定义模型

---

**需要帮助？** 查看主项目 [README](../../README.md) 或提交 Issue。
