from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import pytesseract
from fastapi import HTTPException, status
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader


MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_EXTRACTED_CHARS = 60_000
MAX_IMAGE_PIXELS = 25_000_000
SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class ParsedFile:
    """文件解析结果；模型层只接触文本，不依赖具体文件格式。"""

    name: str
    media_type: str
    size: int
    text: str
    extraction_method: str
    truncated: bool

    def attachment_data(self) -> dict:
        return {
            "name": self.name,
            "media_type": self.media_type,
            "size": self.size,
            "extraction_method": self.extraction_method,
            "extracted_chars": len(self.text),
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class ValidatedUpload:
    name: str
    suffix: str
    media_type: str
    size: int


def validate_upload(filename: str | None, media_type: str | None, content: bytes) -> ValidatedUpload:
    """上传和解析共用同一套文件名、格式与大小校验。"""
    safe_name = Path(filename or "upload").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="不支持该文件格式，请上传 txt、md、csv、pdf、docx 或常见图片。",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="上传文件为空。")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件不能超过 10 MB。")
    return ValidatedUpload(
        name=safe_name,
        suffix=suffix,
        media_type=media_type or "application/octet-stream",
        size=len(content),
    )


def parse_uploaded_file(filename: str | None, media_type: str | None, content: bytes) -> ParsedFile:
    """校验上传内容并提取可交给文本模型分析的文本。"""
    upload = validate_upload(filename, media_type, content)
    safe_name = upload.name
    suffix = upload.suffix

    try:
        if suffix in {".txt", ".md", ".csv"}:
            text, method = _decode_text(content), "文本提取"
        elif suffix == ".pdf":
            text, method = _extract_pdf(content), "PDF 文本提取"
        elif suffix == ".docx":
            text, method = _extract_docx(content), "Word 文本提取"
        else:
            text, method = _extract_image_ocr(content), "图片 OCR"
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文件内容无法解析，请确认文件没有损坏或加密。",
        ) from exc

    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        detail = "没有识别到文字，请上传文字更清晰的图片。" if method == "图片 OCR" else "文件中没有提取到可分析的文字。"
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

    truncated = len(normalized) > MAX_EXTRACTED_CHARS
    if truncated:
        normalized = normalized[:MAX_EXTRACTED_CHARS]
    return ParsedFile(
        name=safe_name,
        media_type=upload.media_type,
        size=upload.size,
        text=normalized,
        extraction_method=method,
        truncated=truncated,
    )


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="文本编码不支持，请使用 UTF-8。")


def _extract_pdf(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="暂不支持加密 PDF。")
    return "\n\n".join(page.extract_text() or "" for page in reader.pages[:100])


def _extract_docx(content: bytes) -> str:
    """DOCX 本质是 OpenXML 压缩包，按 XML 节点读取正文和表格文本。"""
    try:
        with ZipFile(BytesIO(content)) as archive:
            xml_content = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="DOCX 文件无效或已损坏。") from exc

    root = ElementTree.fromstring(xml_content)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _extract_image_ocr(content: bytes) -> str:
    try:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with Image.open(BytesIO(content)) as image:
            image.load()
            languages = pytesseract.get_languages(config="")
            language = "chi_sim+eng" if "chi_sim" in languages else "eng"
            return pytesseract.image_to_string(image.convert("RGB"), lang=language)
    except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="图片格式无效或文件已损坏。") from exc
