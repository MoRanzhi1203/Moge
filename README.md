# Moge（墨格）

对图片进行像素化处理：调整尺寸、按块均值/频数着色、颜色聚类压缩，支持预览与保存。

## 环境要求

- Windows 10/11
- Python 3.9+（CI 覆盖 3.9 / 3.11）

## 安装

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## 运行

```powershell
python main.py
# 或安装后
moge
```

日志写入 `%LOCALAPPDATA%\Moge\logs\app.log`。

## 测试与静态检查

```powershell
ruff check .
pytest --cov=Moge.core --cov-report=term-missing
```

## 打包

```powershell
pyinstaller --noconfirm Moge.spec
```

产物位于 `dist/Moge`。

## 许可

Apache-2.0，详见 LICENSE。
