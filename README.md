# AudiHacks

Automatiza el **Secret Garden** de Audition: cortar lo maduro, sembrar, regar, abonar y levantar los drops.
Usa el mouse real (el juego ignora clics enviados a la ventana) y por eso **debe ejecutarse como administrador**
(Audition corre elevado).

## Instalacion
1. Instalar **Python 3.12** (python.org, marcar "Add Python to PATH").
2. Ejecutar `instalar.bat`.
3. Abrir el juego, iniciar sesion y dejarlo en el **Secret Garden** (ventana de 1024x768, idioma espanol).
4. Ejecutar `iniciar_interfaz.bat` (acepta el aviso de administrador), elegir la planta y pulsar **Iniciar**.

## Uso
- **Detener:** boton Detener o tecla **F12** (para al instante).
- Plantas: Romero (7 min), Menta Verde (23 min), "Alternar" (3 Romero + 1 Menta Verde) o "Por horario" (dia Menta Verde / noche Romero; horas en `config.json`).
- Durante una rafaga no mover el mouse ni escribir. Si lo mueves, espera y retoma solo.
- Si el servidor desconecta, avisa con alarma; no vuelve a iniciar sesion solo.

## Calibracion
Las posiciones (parcelas, herramientas, botones) estan en `config.json` y son para una ventana de 1024x768.
Si tu pantalla se ve distinta, hay que ajustarlas. Las imagenes de `referencias/` sirven para reconocer pantallas.

## Aviso
Automatizar el juego puede ir contra sus normas. Usalo bajo tu propio riesgo.
