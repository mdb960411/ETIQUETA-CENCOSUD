import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import pandas as pd
import pdfplumber
import streamlit as st
from reportlab.graphics.barcode import code128
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


@dataclass
class PurchaseOrderItem:
    pos: str
    codigo: str
    descripcion: str
    unidad: str
    cantidad: int
    precio_unitario: str = ""
    total_cargos: str = ""
    monto_total: str = ""


@dataclass
class PurchaseOrder:
    numero_oc: str
    fecha_emision: str
    fecha_entrega: str
    local_entrega: str
    local_destino: str
    lugar_entrega: str
    comprador: str
    proveedor: str
    items: List[PurchaseOrderItem]


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_oc_from_pdf(file_bytes: bytes) -> PurchaseOrder:
    text_parts = []
    tables = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
            tables.extend(page.extract_tables() or [])

    full_text = "\n".join(text_parts)

    numero_oc = find_first(full_text, r"(?:N[°o]\s*)?Orden de Compra\s+Fecha Emision\s+Fecha Entrega\s*\n.*?\n(\d{8,12})")
    if not numero_oc:
        numero_oc = find_first(full_text, r"\b(5\d{9})\b") or "SIN_OC"

    fecha_emision = find_first(full_text, r"\b(\d{2}/\d{2}/\d{4})\b") or ""
    all_dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", full_text)
    fecha_entrega = all_dates[1] if len(all_dates) > 1 else ""

    local_entrega = find_first(full_text, r"30\s*dias\s+([A-Z]\d{3,4})\s+([A-Z]\d{3,4})") or ""
    local_destino = ""
    match_local = re.search(r"30\s*dias\s+([A-Z]\d{3,4})\s+([A-Z]\d{3,4})", full_text)
    if match_local:
        local_entrega = match_local.group(1)
        local_destino = match_local.group(2)

    lugar_entrega = find_first(full_text, r"Lugar Entrega\s*\n?([A-Z ]+)") or find_first(full_text, r"\b(CD [A-Z]+)\b") or ""
    comprador = find_first(full_text, r"Info\. Comprador\s*\n?([A-Z0-9]+)") or ""
    proveedor = find_first(full_text, r"Info\. Proveedor\s*\n?([A-Z0-9 .]+LTDA\.)") or ""

    items = parse_items_from_tables(tables)
    if not items:
        items = parse_items_from_text(full_text)

    return PurchaseOrder(
        numero_oc=numero_oc,
        fecha_emision=fecha_emision,
        fecha_entrega=fecha_entrega,
        local_entrega=local_entrega,
        local_destino=local_destino,
        lugar_entrega=lugar_entrega,
        comprador=comprador,
        proveedor=proveedor,
        items=items,
    )


def find_first(text: str, pattern: str) -> Optional[str]:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return clean_text(match.group(1)) if match else None


def parse_items_from_tables(tables: list) -> List[PurchaseOrderItem]:
    items: List[PurchaseOrderItem] = []
    for table in tables:
        for row in table:
            cells = [clean_text(str(c)) for c in row if c is not None]
            row_text = " ".join(cells)
            if not re.match(r"^\d+\s+\d{8,}", row_text):
                continue
            parsed = parse_item_line(row_text)
            if parsed:
                items.append(parsed)
    return dedupe_items(items)


def parse_items_from_text(text: str) -> List[PurchaseOrderItem]:
    items: List[PurchaseOrderItem] = []
    for line in text.splitlines():
        parsed = parse_item_line(clean_text(line))
        if parsed:
            items.append(parsed)
    return dedupe_items(items)


def parse_item_line(line: str) -> Optional[PurchaseOrderItem]:
    # Example:
    # 40 99999900076779 TE CONVIENE 1/4 MERCURIO 50 X 35 CS 90 31.125 0 2.801.250
    pattern = re.compile(
        r"^(\d+)\s+"
        r"(\d{8,})\s+"
        r"(.+?)\s+"
        r"(CS|UN|CJ|PAQ|KG|LT)\s+"
        r"(\d+)\s+"
        r"([\d.]+)\s+"
        r"([\d.]+)\s+"
        r"([\d.]+)$",
        flags=re.IGNORECASE,
    )
    match = pattern.match(line)
    if not match:
        return None
    return PurchaseOrderItem(
        pos=match.group(1),
        codigo=match.group(2),
        descripcion=clean_text(match.group(3)).upper(),
        unidad=match.group(4).upper(),
        cantidad=int(match.group(5)),
        precio_unitario=match.group(6),
        total_cargos=match.group(7),
        monto_total=match.group(8),
    )


def dedupe_items(items: List[PurchaseOrderItem]) -> List[PurchaseOrderItem]:
    seen = set()
    result = []
    for item in items:
        key = (item.pos, item.codigo, item.descripcion, item.cantidad)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def safe_filename(text: str, max_len: int = 80) -> str:
    text = re.sub(r"[^A-Za-z0-9_ -]", "", text)
    text = re.sub(r"\s+", "_", text).strip("_")
    return text[:max_len] or "item"


def generate_item_pdf(po: PurchaseOrder, item: PurchaseOrderItem, copies_per_page: int = 2) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    label_w = width - 24 * mm
    label_h = 125 * mm if copies_per_page == 2 else height - 24 * mm
    margin_x = 12 * mm
    top_y = height - 12 * mm
    total = item.cantidad
    digits = max(3, len(str(total)))

    for idx in range(1, total + 1):
        slot = (idx - 1) % copies_per_page
        if slot == 0 and idx > 1:
            c.showPage()
        y_top = top_y - slot * (label_h + 8 * mm)
        draw_label(c, margin_x, y_top - label_h, label_w, label_h, po, item, idx, total, digits)

    c.save()
    return buffer.getvalue()


def draw_label(c, x, y, w, h, po: PurchaseOrder, item: PurchaseOrderItem, idx: int, total: int, digits: int):
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.2)
    c.rect(x, y, w, h)

    pad = 7 * mm
    left = x + pad
    right = x + w - pad
    top = y + h - pad

    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(x + w / 2, top - 2 * mm, "ETIQUETA DE BULTO")

    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, top - 16 * mm, po.local_entrega or "N725")
    c.drawRightString(right, top - 16 * mm, f"OC {po.numero_oc}")

    barcode_value = f"{po.numero_oc}-{item.pos}-{idx:0{digits}d}"
    bc = code128.Code128(barcode_value, barHeight=18 * mm, barWidth=0.38 * mm)
    bc.drawOn(c, x + (w - bc.width) / 2, top - 41 * mm)
    c.setFont("Helvetica", 9)
    c.drawCentredString(x + w / 2, top - 44 * mm, barcode_value)

    c.setFont("Helvetica-Bold", 13)
    c.drawString(left, top - 57 * mm, f"ITEM/POS: {item.pos}")
    c.drawRightString(right, top - 57 * mm, f"CODIGO: {item.codigo}")

    c.setFont("Helvetica-Bold", 15)
    desc_lines = wrap_text(item.descripcion, 48)
    for n, line in enumerate(desc_lines[:2]):
        c.drawCentredString(x + w / 2, top - (72 + n * 7) * mm, line)

    c.setFont("Helvetica", 11)
    c.drawString(left, y + 31 * mm, f"ENTREGA: {po.lugar_entrega or '-'}")
    c.drawRightString(right, y + 31 * mm, f"FECHA: {po.fecha_entrega or '-'}")

    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(x + w / 2, y + 18 * mm, f"BULTO {idx:0{digits}d}/{total:0{digits}d}")

    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(x + w / 2, y + 8 * mm, "BULTO FRAGIL")


def wrap_text(text: str, max_chars: int) -> List[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def build_zip(po: PurchaseOrder, selected_items: List[PurchaseOrderItem]) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in selected_items:
            pdf_bytes = generate_item_pdf(po, item)
            filename = (
                f"OC_{safe_filename(po.numero_oc)}_Item_{safe_filename(item.pos)}_"
                f"{safe_filename(item.descripcion)}_{item.cantidad}_etiquetas.pdf"
            )
            zf.writestr(filename, pdf_bytes)
    return zip_buffer.getvalue()


def items_to_dataframe(items: List[PurchaseOrderItem]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Pos": item.pos,
            "Codigo": item.codigo,
            "Descripcion": item.descripcion,
            "Unidad": item.unidad,
            "Cantidad": item.cantidad,
            "Etiquetas": item.cantidad,
        }
        for item in items
    ])


st.set_page_config(page_title="Generador de etiquetas Cencosud", page_icon="🏷️", layout="wide")
st.title("Generador de etiquetas Cencosud / Faldones")
st.caption("Sube una orden de compra PDF y genera un PDF individual por item, con etiquetas numeradas.")

uploaded_file = st.file_uploader("Orden de compra PDF", type=["pdf"])

if uploaded_file:
    file_bytes = uploaded_file.read()
    try:
        po = parse_oc_from_pdf(file_bytes)
    except Exception as exc:
        st.error(f"No se pudo leer la OC: {exc}")
        st.stop()

    st.subheader("Datos detectados")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("OC", po.numero_oc)
    c2.metric("Fecha entrega", po.fecha_entrega or "-")
    c3.metric("Local", po.local_entrega or "-")
    c4.metric("Items", len(po.items))

    if not po.items:
        st.warning("No se detectaron items. Revisa que el PDF tenga una tabla similar al formato Cencosud.")
        st.stop()

    st.subheader("Vista previa de items")
    df = items_to_dataframe(po.items)
    edited_df = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        disabled=["Pos", "Codigo", "Descripcion", "Unidad", "Cantidad"],
        column_config={"Etiquetas": st.column_config.NumberColumn(min_value=1, step=1)},
    )

    # Keep business rule: quantity equals labels. The editable grid is shown for future flexibility,
    # but this MVP still uses Cantidad as source of truth.
    selected_labels = st.multiselect(
        "Items a generar",
        options=[f"{item.pos} - {item.descripcion}" for item in po.items],
        default=[f"{item.pos} - {item.descripcion}" for item in po.items],
    )
    selected_positions = {label.split(" - ")[0] for label in selected_labels}
    selected_items = [item for item in po.items if item.pos in selected_positions]

    total_labels = sum(item.cantidad for item in selected_items)
    st.info(f"Se generaran {len(selected_items)} PDF individuales y {total_labels} etiquetas en total.")

    if st.button("Generar ZIP con PDF individuales", type="primary"):
        zip_bytes = build_zip(po, selected_items)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            label="Descargar ZIP",
            data=zip_bytes,
            file_name=f"etiquetas_OC_{safe_filename(po.numero_oc)}_{timestamp}.zip",
            mime="application/zip",
        )
else:
    st.info("Carga una OC PDF para comenzar.")
