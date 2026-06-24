# Generador de etiquetas Cencosud / Faldones

Version MVP en Streamlit.

## Que hace

- Sube una orden de compra PDF de Cencosud.
- Extrae numero de OC, fecha, local/CD y lineas de producto.
- Genera un PDF individual por cada item.
- La cantidad pedida de cada item equivale a la cantidad de etiquetas.
- Numera cada etiqueta como BULTO 001/090, BULTO 002/090, etc.
- Entrega un ZIP con todos los PDF.

## Ejecutar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy en Streamlit Community Cloud

1. Crear repositorio en GitHub.
2. Subir `app.py` y `requirements.txt`.
3. Entrar a Streamlit Community Cloud.
4. Crear app apuntando al repo y archivo `app.py`.

## Notas

Este MVP parsea OCs con formato similar al PDF de Cencosud usado como ejemplo. Para hacerlo productivo conviene agregar:

- Base maestra de productos.
- Validacion contra SKU interno/EAN/DUN.
- Diseno final exacto de etiqueta segun impresora.
- Soporte para mas formatos de OC.
