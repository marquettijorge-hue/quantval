# QuantVal Institutional - Plataforma Cuantitativa de Valuación

Motor cuantitativo institucional de valuación fundamental de acciones:
- Monte Carlo (10.000 iteraciones)
- Reverse DCF
- Modo Cara a Cara (Head-to-Head) con Radar superpuesto de 5 ejes y TIR proyectada a 5 años
- Papers académicos: Joseph Piotroski (2000), Christopher Mayer (100-Baggers), Richard Sloan (1996), Robert Novy-Marx (2013), Aswath Damodaran y Bruce Greenwald (EPV).

## Despliegue en Render
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn server:app --host 0.0.0.0 --port $PORT`
