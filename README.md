# Generador de Etiquetas de Bulto - Cencosud

App web en Streamlit para generar etiquetas de bulto desde una Orden de Compra Cencosud en PDF.

## Funcionalidades

- Carga de OC en PDF.
- Deteccion automatica de items.
- Cantidad pedida = cantidad de etiquetas.
- Un PDF individual por item.
- Etiquetas numeradas: 1 / total.
- OP interna editable por item, impresa como codigo inferior.
- EAN13 y DUN14 se buscan automaticamente en la matriz original usando el codigo de producto de la OC.
- Previsualizacion antes de descargar.
- Descarga de PDF individual o ZIP con todos los PDFs.

## Ejecutar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Desplegar en Streamlit Community Cloud

1. Sube estos archivos a un repositorio de GitHub.
2. En Streamlit Cloud, selecciona el repositorio.
3. Main file path: `app.py`.
4. Deploy.

## Nota sobre codigos de barra

La app incluye la base maestra extraida desde `ETIQUETAS CENCOSUD - FALDONES CD.xlsx`.
El codigo de producto de la OC se cruza contra el DUN14 de la matriz y desde ahi se obtiene:

- EAN13 para el codigo de barra superior.
- DUN14 para el codigo de barra inferior, impreso como `(01)DUN14`.

Si aparece un codigo no existente en la matriz, la app muestra una advertencia.
