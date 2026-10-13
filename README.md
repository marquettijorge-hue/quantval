# QuantVal Pro — análisis histórico con fuentes

Recurso gratuito de @accionesargentinas. Consulta datos anuales estándar en USD de SEC EDGAR y compara indicadores sin emitir recomendaciones ni estimar retornos.

## Alcance de esta versión (3.0.0)

- Empresa, actividad declarada ante la SEC y último ejercicio anual disponible.
- Ingresos, crecimiento histórico y márgenes calculados desde períodos comparables.
- Flujo de caja de operaciones menos inversión reportada, con definición e inputs visibles.
- Rama financiera: margen neto, ROE contable y patrimonio/activos; sin FCF industrial.
- Fuentes por indicador: valor de cada input, período, fecha de publicación y documento.
- Comparador descriptivo, copiar resumen y enlaces por ticker o pareja.
- Cotización opcional de Yahoo Finance con timestamp, moneda y posible demora.
- CTA configurable hacia el Taller o contacto real en Instagram.

No calcula fair value, MoS, TIR, consenso, Piotroski, Altman, Kelly, scores, historial de P/E ni benchmarks fijos. Las funciones y sus dependencias se retiraron del lanzamiento; la versión anterior permanece en el historial de Git.

Se comparan **ejercicios anuales**, no TTM. Pueden existir resultados trimestrales más recientes. Los conceptos personalizados, emisores sin estados estándar en USD, ETF y algunos tipos de activos no están cubiertos. Un campo ausente no se convierte en cero.

## Ejecutar y probar

Python 3.11+:

    python -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest -q
    node --test tests/frontend.test.cjs
    .venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000

En Windows usar .venv\Scripts\python y .venv\Scripts\pip.
Los tests unitarios utilizan extractos de documentos SEC congelados al 13/10/2026, no cotizaciones vivas. No realizan consultas de red al importar archivos de test.

## Render

Mantiene los comandos existentes:

- Build: pip install -r requirements.txt
- Start: uvicorn server:app --host 0.0.0.0 --port $PORT
- Health check: /health

Variables opcionales:

- SEC_USER_AGENT: identificación del proyecto con un contacto válido conforme a las pautas de acceso de SEC. El valor por defecto identifica este repositorio público.
- TALLER_URL: URL HTTPS real del Taller. Sin ella, el botón dice «Pedime información del Taller» y abre el perfil de Instagram.
- RENDER_GIT_COMMIT: Render la proporciona; /health y el footer la muestran para identificar el despliegue. Fuera de Render se admite COMMIT_SHA.

Antes de lanzar, confirmar en /health **version 3.0.0**, **model_version annual-sec-v1** y el commit que se pretendía desplegar. Una respuesta de la versión 2.4.0 no contiene este cambio.

Prueba normal de producción, explícita y limitada a cinco empresas:

    python test_production.py https://quantval.onrender.com

Primero comprueba la versión desplegada. Luego consulta AAPL, MSFT, NVDA, JPM y NFLX. No es una prueba de carga.

## Fuentes y metodología

Los APIs de la SEC no requieren clave:
https://www.sec.gov/search-filings/edgar-application-programming-interfaces

Se usan el directorio público de tickers, submissions y companyfacts. Se eligen períodos anuales de 330–380 días y comparativos anuales de duración similar; no se suman cifras trimestrales/YTD. Se conserva la última divulgación disponible para cada período. La extracción puede omitir conceptos personalizados; siempre mostrar el documento original.

Los conceptos de inversión pueden incluir intangibles en determinados emisores. La tarjeta informa el tag, valor y definición aplicada. No equiparar automáticamente ese flujo con un FCF a la firma para un DCF.

ROE contable = utilidad neta / promedio de patrimonio inicial y final, solo cuando ambos saldos son positivos y hay datos. Patrimonio/activos no equivale a CET1 ni demuestra adecuación regulatoria.

Caché de resultados por ticker y versión del modelo, 15 minutos, hasta 128 entradas. Dos análisis de proveedor simultáneos; consultas idénticas concurrentes se deduplican. Se espacian los accesos a SEC. No se evaden bloqueos ni se inventan datos ante fallos. El precio lleva su propio timestamp y puede faltar sin bloquear los balances.

## Validación y límites de lanzamiento

Las consultas individuales y tests funcionales no prueban capacidad para miles de usuarios. Verificar acceso a las fuentes desde Render, recorrido en celular y navegador de Instagram y funcionamiento de Copiar en ese navegador antes de una distribución masiva. Esta versión no envía eventos a un servicio de analytics externo; se pueden añadir posteriormente mediante una integración autorizada.
