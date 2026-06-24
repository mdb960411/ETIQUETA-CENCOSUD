# Generador de Etiquetas de Bulto - Cencosud

MVP en Streamlit para subir una Orden de Compra Cencosud en PDF y generar etiquetas de bulto.

## Qué hace

- Lee automáticamente la OC PDF.
- Detecta número de OC, fechas, local, lugar de entrega e ítems.
- Usa la regla: cantidad pedida = cantidad de etiquetas.
- Permite previsualizar una etiqueta antes de generar.
- Permite corregir descripción, cantidad, EAN13 y DUN14 antes de imprimir.
- Genera un PDF individual por cada ítem.
- Numera las etiquetas: `1 / 90`, `2 / 90`, etc.
- Exporta un ZIP con todos los PDFs.
- Diseño visual basado en la etiqueta original: encabezado, N725, campaña, EAN13, DUN14, logo Inser, “BULTO FRAGIL” y código inferior.

## Ejecutar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Publicar en Streamlit Community Cloud

1. Crea un repositorio en GitHub.
2. Sube estos archivos.
3. Entra a https://share.streamlit.io/
4. Conecta el repositorio.
5. Selecciona `app.py` como archivo principal.
6. Deploy.

## Base maestra de códigos

En `app.py` existe un diccionario inicial llamado `PRODUCT_EAN13`. Ahí puedes agregar o corregir el EAN13 por código de producto Cencosud.

Ejemplo:

```python
PRODUCT_EAN13 = {
    "99999950803493": "2082001865930",
}
```

Más adelante puede reemplazarse por carga de Excel, Google Sheets o base de datos.
