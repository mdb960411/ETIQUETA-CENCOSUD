import io
import re
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime
from typing import List, Optional, Dict

import pandas as pd
import pdfplumber
import streamlit as st
import streamlit.components.v1 as components
from reportlab.graphics.barcode import code128, eanbc
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


PRODUCT_EAN13: Dict[str, str] = {
    # Se puede ampliar desde una base maestra. Valores iniciales para la OC de prueba.
    "99999950803493": "2082001865930",
}

DEFAULT_BOTTOM_CODE = "617898"
DEFAULT_CAMPAIGN_PREFIX = "FALDONES_CENCOSUD OC"


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
    ean13: str = ""
    dun14: str = ""


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


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def guess_ean13(codigo: str) -> str:
    if codigo in PRODUCT_EAN13:
        return PRODUCT_EAN13[codigo]
    digits = only_digits(codigo)
    if len(digits) >= 13:
        return digits[-13:]
    return digits.zfill(13)


def guess_dun14(codigo: str) -> str:
    digits = only_digits(codigo)
    if len(digits) >= 14:
        return digits[-14:]
    return digits.zfill(14)


def normalize_item(item: PurchaseOrderItem) -> PurchaseOrderItem:
    return replace(
        item,
        ean13=item.ean13 or guess_ean13(item.codigo),
        dun14=item.dun14 or guess_dun14(item.codigo),
    )


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

    all_dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", full_text)
    fecha_emision = all_dates[0] if all_dates else ""
    fecha_entrega = all_dates[1] if len(all_dates) > 1 else ""

    local_entrega = ""
    local_destino = ""
    match_local = re.search(r"30\s*dias\s+([A-Z]\d{3,4})\s+([A-Z]\d{3,4})", full_text)
    if match_local:
        local_entrega = match_local.group(1)
        local_destino = match_local.group(2)

    lugar_entrega = find_first(full_text, r"\b(CD [A-Z]+)\b") or ""
    comprador = find_first(full_text, r"Info\. Comprador\s*\n?([A-Z0-9]+)") or ""
    proveedor = find_first(full_text, r"Info\. Proveedor\s*\n?([A-Z0-9 .]+LTDA\.)") or ""

    items = parse_items_from_tables(tables) or parse_items_from_text(full_text)
    items = [normalize_item(i) for i in items]

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


def truncate_desc(text: str, max_chars: int = 32) -> str:
    text = clean_text(text).upper()
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def items_to_dataframe(items: List[PurchaseOrderItem]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Pos": item.pos,
            "Código": item.codigo,
            "Descripción": item.descripcion,
            "Cant. (Etiquetas)": item.cantidad,
            "EAN13": item.ean13,
            "DUN14": item.dun14,
        }
        for item in items
    ])


def df_to_items(df: pd.DataFrame) -> List[PurchaseOrderItem]:
    items: List[PurchaseOrderItem] = []
    for _, row in df.iterrows():
        items.append(PurchaseOrderItem(
            pos=str(row["Pos"]),
            codigo=only_digits(str(row["Código"])),
            descripcion=clean_text(str(row["Descripción"])).upper(),
            unidad="CS",
            cantidad=int(row["Cant. (Etiquetas)"]),
            ean13=only_digits(str(row.get("EAN13", ""))),
            dun14=only_digits(str(row.get("DUN14", ""))),
        ))
    return items


def label_svg(po: PurchaseOrder, item: PurchaseOrderItem, index: int, total: int, bottom_code: str) -> str:
    desc = truncate_desc(item.descripcion, 38)
    label_no = f"{index} / {total}"
    ean_text = format_ean_text(item.ean13)
    dun_text = f"(01){item.dun14}"
    campaign = f"CAMPAÑA: {DEFAULT_CAMPAIGN_PREFIX} {po.numero_oc}"
    local = po.local_entrega or "N725"
    return f"""
    <div class=\"label-preview\">
      <div class=\"row top\"><div class=\"title\">ETIQUETA DE BULTO</div><div class=\"local\">{local}</div></div>
      <div class=\"row item\"><div class=\"count\">{label_no}</div><div class=\"desc\">{item.pos} {desc}</div></div>
      <div class=\"campaign\">{campaign}</div>
      <div class=\"body\">
        <div class=\"ean-wrap\"><div class=\"barcode ean\"></div><div class=\"ean-text\">{ean_text}</div></div>
        <div class=\"dun-wrap\"><div class=\"barcode dun\"></div><div class=\"dun-text\">{dun_text}</div></div>
      </div>
      <div class=\"fragile\"><div class=\"logo\"><span></span><b>inser</b><em>IMPRESORES</em></div><div>BULTO FRAGIL</div></div>
      <div class=\"bottom-code\">{bottom_code}</div>
    </div>
    """


def preview_component(po: PurchaseOrder, item: PurchaseOrderItem, index: int, bottom_code: str):
    total = item.cantidad
    html = f"""
    <style>
      .label-preview {{ width: min(100%, 445px); aspect-ratio: 445/593; margin: 0 auto; background:#fff; color:#000; border:2px solid #000; font-family: Arial, Helvetica, sans-serif; box-sizing:border-box; }}
      .label-preview * {{ box-sizing:border-box; }}
      .row {{ display:grid; border-bottom:2px solid #000; }}
      .top {{ grid-template-columns: 1fr 80px; height: 40px; }}
      .title {{ display:flex; align-items:center; justify-content:center; font-weight:800; font-size:21px; text-decoration:underline; }}
      .local {{ border-left:2px solid #000; display:flex; align-items:center; justify-content:center; font-size:16px; }}
      .item {{ grid-template-columns: 80px 1fr; height: 40px; }}
      .count {{ border-right:2px solid #000; display:flex; align-items:center; justify-content:center; color:#cfcfcf; font-weight:700; font-size:16px; }}
      .desc {{ display:flex; align-items:center; justify-content:center; font-weight:800; font-size:16px; text-align:center; }}
      .campaign {{ height:32px; display:flex; align-items:center; justify-content:center; font-style:italic; font-weight:800; font-size:15px; border-bottom:0; }}
      .body {{ height:410px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:48px; padding-top:6px; }}
      .barcode {{ background: repeating-linear-gradient(90deg,#000 0 3px,#fff 3px 5px,#000 5px 7px,#fff 7px 11px,#000 11px 12px,#fff 12px 15px); }}
      .ean {{ width:235px; height:86px; }}
      .dun {{ width:338px; height:93px; }}
      .ean-text {{ text-align:center; font-size:28px; line-height:24px; letter-spacing:2px; margin-top:-8px; }}
      .dun-text {{ text-align:center; font-size:27px; line-height:27px; margin-top:0; }}
      .fragile {{ height:40px; border-top:2px solid #000; border-bottom:2px solid #000; display:grid; grid-template-columns:130px 1fr; align-items:center; }}
      .fragile > div:last-child {{ color:#f00; font-weight:900; font-size:26px; text-align:left; }}
      .logo {{ padding-left:12px; position:relative; color:#1261a6; }}
      .logo span {{ display:inline-block; width:22px; height:26px; vertical-align:middle; margin-right:4px; background:linear-gradient(90deg,#1e63ff 0 25%,#26b64b 25% 50%,#ffcf30 50% 72%,#e9463f 72%); }}
      .logo b {{ font-size:28px; letter-spacing:-1px; }}
      .logo em {{ display:block; font-size:7px; font-style:normal; letter-spacing:2px; margin-left:37px; margin-top:-5px; color:#18416b; }}
      .bottom-code {{ height:25px; display:flex; align-items:center; justify-content:center; font-weight:900; font-size:17px; }}
    </style>
    {label_svg(po, item, index, bottom_code)}
    """
    components.html(html, height=650, scrolling=False)


def format_ean_text(ean13: str) -> str:
    digits = only_digits(ean13).zfill(13)[-13:]
    return f"{digits[0]}  {digits[1:7]}  {digits[7:]}"


def draw_barcode_ean13(c, value: str, x: float, y: float, width_target: float, height_target: float):
    digits = only_digits(value).zfill(13)[-13:]
    bc = eanbc.Ean13BarcodeWidget(digits)
    bounds = bc.getBounds()
    bw = bounds[2] - bounds[0]
    bh = bounds[3] - bounds[1]
    scale = min(width_target / bw, height_target / bh)
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF
    d = Drawing(width_target, height_target)
    bc.x = (width_target - bw * scale) / (2 * scale)
    bc.y = 0
    bc.barHeight = height_target / scale * 0.72
    d.add(bc)
    d.scale(scale, scale)
    renderPDF.draw(d, c, x, y)


def draw_barcode_code128(c, value: str, x: float, y: float, width_target: float, height_target: float):
    bc = code128.Code128(value, barHeight=height_target, barWidth=0.45 * mm)
    scale = min(1.0, width_target / bc.width)
    c.saveState()
    c.translate(x + (width_target - bc.width * scale) / 2, y)
    c.scale(scale, 1)
    bc.drawOn(c, 0, 0)
    c.restoreState()


def generate_item_pdf(po: PurchaseOrder, item: PurchaseOrderItem, bottom_code: str) -> bytes:
    buffer = io.BytesIO()
    page_size = landscape(A4)
    c = canvas.Canvas(buffer, pagesize=page_size)
    page_w, page_h = page_size

    margin_x = 8 * mm
    margin_y = 10 * mm
    gap = 8 * mm
    label_w = (page_w - 2 * margin_x - gap) / 2
    label_h = page_h - 2 * margin_y
    total = item.cantidad

    for idx in range(1, total + 1):
        slot = (idx - 1) % 2
        if slot == 0 and idx > 1:
            c.showPage()
        x = margin_x + slot * (label_w + gap)
        y = margin_y
        draw_label(c, x, y, label_w, label_h, po, item, idx, total, bottom_code)

    c.save()
    return buffer.getvalue()


def draw_inser_logo(c, x, y, w, h):
    c.saveState()
    icon_w = 9 * mm
    icon_h = 9 * mm
    colors_icon = [colors.HexColor("#1f62ff"), colors.HexColor("#28b84a"), colors.HexColor("#ffd23a"), colors.HexColor("#e23b3b")]
    for i, col in enumerate(colors_icon):
        c.setFillColor(col)
        c.rect(x + i * icon_w / 4, y + 2 * mm, icon_w / 3, icon_h, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#1261a6"))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x + 11 * mm, y + 5 * mm, "inser")
    c.setFont("Helvetica-Bold", 3.8)
    c.drawString(x + 12 * mm, y + 2.5 * mm, "I M P R E S O R E S")
    c.restoreState()


def draw_label(c, x, y, w, h, po: PurchaseOrder, item: PurchaseOrderItem, idx: int, total: int, bottom_code: str):
    c.setStrokeColor(colors.black)
    c.setFillColor(colors.white)
    c.setLineWidth(1.2)
    c.rect(x, y, w, h, stroke=1, fill=0)

    top_h = 16 * mm
    item_h = 16 * mm
    campaign_h = 12 * mm
    fragile_h = 16 * mm
    bottom_h = 8 * mm
    local_w = 28 * mm
    count_w = 28 * mm

    y_top = y + h
    # Top row
    c.line(x, y_top - top_h, x + w, y_top - top_h)
    c.line(x + w - local_w, y_top, x + w - local_w, y_top - top_h)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(x + (w - local_w) / 2, y_top - 10.5 * mm, "ETIQUETA DE BULTO")
    c.line(x + (w - local_w) / 2 - 28 * mm, y_top - 11.6 * mm, x + (w - local_w) / 2 + 28 * mm, y_top - 11.6 * mm)
    c.setFont("Helvetica", 10)
    c.drawCentredString(x + w - local_w / 2, y_top - 10.5 * mm, po.local_entrega or "N725")

    # Item row
    y_item = y_top - top_h
    c.line(x, y_item - item_h, x + w, y_item - item_h)
    c.line(x + count_w, y_item, x + count_w, y_item - item_h)
    c.setFillColor(colors.HexColor("#cfcfcf"))
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x + count_w / 2, y_item - 10 * mm, f"{idx} / {total}")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + count_w + (w - count_w) / 2, y_item - 10 * mm, f"{item.pos} {truncate_desc(item.descripcion, 34)}")

    # Campaign
    y_campaign = y_item - item_h
    c.setFont("Helvetica-BoldOblique", 8.8)
    c.drawCentredString(x + w / 2, y_campaign - 8 * mm, f"CAMPAÑA: {DEFAULT_CAMPAIGN_PREFIX} {po.numero_oc}")

    # Barcodes
    body_top = y_campaign - campaign_h
    draw_barcode_ean13(c, item.ean13, x + w * 0.25, body_top - 35 * mm, w * 0.50, 28 * mm)
    c.setFont("Helvetica", 15)
    c.drawCentredString(x + w / 2, body_top - 39 * mm, format_ean_text(item.ean13))

    draw_barcode_code128(c, item.dun14, x + w * 0.12, body_top - 82 * mm, w * 0.76, 30 * mm)
    c.setFont("Helvetica", 15)
    c.drawCentredString(x + w / 2, body_top - 88 * mm, f"(01){item.dun14}")

    # Fragile row
    y_fragile_top = y + bottom_h + fragile_h
    c.line(x, y_fragile_top, x + w, y_fragile_top)
    c.line(x, y + bottom_h, x + w, y + bottom_h)
    draw_inser_logo(c, x + 6 * mm, y + bottom_h + 2 * mm, 40 * mm, 12 * mm)
    c.setFillColor(colors.red)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(x + w * 0.62, y + bottom_h + 5 * mm, "BULTO FRAGIL")
    c.setFillColor(colors.black)

    # Bottom code
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + w / 2, y + 2.2 * mm, bottom_code)


def build_zip(po: PurchaseOrder, selected_items: List[PurchaseOrderItem], bottom_code: str) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in selected_items:
            pdf_bytes = generate_item_pdf(po, item, bottom_code)
            filename = (
                f"OC_{safe_filename(po.numero_oc)}_Item_{safe_filename(item.pos)}_"
                f"{safe_filename(item.descripcion)}_{item.cantidad}_etiquetas.pdf"
            )
            zf.writestr(filename, pdf_bytes)
    return zip_buffer.getvalue()


def apply_sidebar_styles():
    st.markdown(
        """
        <style>
          .block-container { padding-top: 1.2rem; }
          [data-testid="stSidebar"] { min-width: 330px; }
          .small-caption { color:#5c677a; font-size:12px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="Generador de Etiquetas de Bulto - Cencosud", page_icon="🏷️", layout="wide")
apply_sidebar_styles()

st.title("🏷️ Generador de Etiquetas de Bulto - Cencosud")
st.caption("Sube una orden de compra PDF, revisa la previsualización y descarga un ZIP con un PDF individual por ítem.")

with st.sidebar:
    st.subheader("1. Subir Orden de Compra (PDF)")
    uploaded_file = st.file_uploader("Arrastra tu PDF aquí", type=["pdf"], label_visibility="collapsed")
    st.divider()

if not uploaded_file:
    st.info("Carga una OC PDF para comenzar.")
    st.stop()

file_bytes = uploaded_file.read()
try:
    po = parse_oc_from_pdf(file_bytes)
except Exception as exc:
    st.error(f"No se pudo leer la OC: {exc}")
    st.stop()

if not po.items:
    st.warning("No se detectaron ítems. Revisa que el PDF tenga una tabla similar al formato Cencosud.")
    st.stop()

with st.sidebar:
    st.success(f"Archivo cargado correctamente: {uploaded_file.name}")
    st.subheader("2. Información de la Orden")
    po.numero_oc = st.text_input("N° Orden de Compra", po.numero_oc)
    po.fecha_emision = st.text_input("Fecha Emisión", po.fecha_emision)
    po.fecha_entrega = st.text_input("Fecha Entrega", po.fecha_entrega)
    po.local_entrega = st.text_input("Cod. Local Entrega", po.local_entrega or "N725")
    po.lugar_entrega = st.text_input("Lugar Entrega", po.lugar_entrega)
    bottom_code = st.text_input("Código inferior etiqueta", DEFAULT_BOTTOM_CODE)

    st.subheader("3. Ítems detectados")
    st.dataframe(items_to_dataframe(po.items)[["Pos", "Código", "Descripción", "Cant. (Etiquetas)"]], hide_index=True, use_container_width=True, height=210)
    st.info(f"Total de etiquetas a generar: {sum(i.cantidad for i in po.items)}\n\nSe generará un PDF individual por cada ítem.")

st.markdown("---")
tab_preview, tab_items = st.tabs(["👁️ PREVISUALIZACIÓN", "▦ TABLA DE ÍTEMS"])

with tab_items:
    st.write("Puedes corregir descripción, cantidad, EAN13 o DUN14 antes de generar los PDFs.")
    edited_df = st.data_editor(
        items_to_dataframe(po.items),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Cant. (Etiquetas)": st.column_config.NumberColumn(min_value=1, step=1),
            "EAN13": st.column_config.TextColumn(help="Código de barra superior"),
            "DUN14": st.column_config.TextColumn(help="Código de barra inferior, se imprime como (01)DUN14"),
        },
    )
    po.items = [normalize_item(i) for i in df_to_items(edited_df)]

with tab_preview:
    col_a, col_b = st.columns([2, 1])
    item_options = {f"Pos {i.pos} - {i.descripcion} ({i.cantidad} etiquetas)": i for i in po.items}
    with col_a:
        selected_label = st.selectbox("Seleccionar ítem:", list(item_options.keys()))
    selected_item = item_options[selected_label]
    with col_b:
        preview_index = st.number_input("Ir a etiqueta #:", min_value=1, max_value=selected_item.cantidad, value=1, step=1)

    preview_component(po, selected_item, int(preview_index), bottom_code)
    st.info(f"Vista previa: Etiqueta {int(preview_index)} de {selected_item.cantidad} para el ítem '{selected_item.descripcion}'.")

    c1, c2 = st.columns([1, 1])
    with c1:
        one_pdf = generate_item_pdf(po, selected_item, bottom_code)
        st.download_button(
            "Descargar PDF de este ítem",
            data=one_pdf,
            file_name=f"OC_{safe_filename(po.numero_oc)}_Item_{safe_filename(selected_item.pos)}_{safe_filename(selected_item.descripcion)}.pdf",
            mime="application/pdf",
        )
    with c2:
        if st.button("Generar todos los PDFs", type="primary", use_container_width=True):
            zip_bytes = build_zip(po, po.items, bottom_code)
            st.session_state["zip_bytes"] = zip_bytes
            st.session_state["zip_name"] = f"etiquetas_OC_{safe_filename(po.numero_oc)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

    if "zip_bytes" in st.session_state:
        st.download_button(
            "⬇️ Descargar ZIP",
            data=st.session_state["zip_bytes"],
            file_name=st.session_state["zip_name"],
            mime="application/zip",
            use_container_width=True,
        )
