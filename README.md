<p align="center">
  <img src="assets/icono.png" width="120" alt="AudiHacks">
</p>

<h1 align="center">AudiHacks</h1>

<p align="center">
  <b>Tu Secret Garden de Audition, trabajando solo.</b><br>
  Corta, siembra, riega, abona y levanta los drops sin que muevas un dedo.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-7c3aed?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-ec4899?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/interfaz-oscura-111827" alt="Interfaz oscura">
</p>

---

## Qué hace

- **Cosecha a tiempo:** corta cada planta cuando madura, siembra Romero o Menta Verde, la riega y la abona.
- **Drops rápidos:** levanta solo los sacos que hay, sin perder tiempo en parcelas vacías.
- **Se recupera solo:** si el juego se cae o sale «No hay respuesta del servidor», cierra el juego y vuelve a entrar
  (lanzador → JUGAR → login → jardín). Acepta los cuadros con botón circular.
- **Respeta lo tuyo:** no toca las parcelas que marques como plantadas a mano.
- **Interfaz compacta:** negra con detalles morados y rosas, con cuenta regresiva, totales, horas trabajadas y sonido.

## Instalación (un solo paso)

1. Descargar la carpeta (`git clone https://github.com/LisaRamirez/audition.git`, o el ZIP y descomprimirlo).
2. Doble clic en **`instalar.bat`**. Hace todo solo:
   - instala Python 3.12 si no lo tienes (con winget) y las librerías,
   - crea las tareas de iniciar/detener (pide el aviso de administrador **una vez**),
   - deja el acceso **«AudiHacks»** con su icono en el Escritorio y abre la interfaz.
3. Tener el juego abierto, con la sesión iniciada, en el **Secret Garden** (ventana 1024×768, español).

Después se abre siempre con el acceso **«AudiHacks»** del Escritorio (acepta el aviso de administrador).

## Primer uso (todo desde la interfaz)

1. **Pestaña Cuenta:** escribe tu **ID de usuario** y tu **contraseña** y pulsa **Guardar cuenta**.
   La contraseña se guarda cifrada con Windows, solo para tu usuario de este PC, y no sale del PC.
   - Marca **«Reingresar solo si me saca del juego»**.
   - Pulsa **Detectar** junto a «Lanzador (Patcher.exe)» para que encuentre el lanzador de Audition.
2. **Pestaña Referencias:** guarda las imágenes de reconocimiento **solo con la pantalla pedida a la vista**
   (la interfaz pregunta antes de guardar):
   - *Pantalla de login*: la que sale al abrir el juego, con el cuadro «Ingresar». **Hazlo una vez**, o la
     primera vez que el juego te saque al login.
   - *Panel de semillas*: el que se abre al pulsar el saquito de semillas.
   - Los cuadros azules con botón circular («No hay respuesta del servidor», etc.) se reconocen solos.
3. **Pestaña Parcelas:** marca las parcelas que plantaste tú a mano. El programa **no las toca**.
4. Elige la planta y pulsa **Iniciar**.

## Uso diario

- **Iniciar / Detener** en la interfaz, o **F12** (parada de emergencia al instante).
- Plantas: Romero (7 min), Menta Verde (23 min), «Alternar» (3 Romero + 1 Menta Verde) o «Por horario»
  (día Menta Verde / noche Romero). El modo por horario y alternar necesitan abrir la interfaz como administrador.
- La **Menta Verde** se ve igual joven que madura, así que corta **por reloj**: 23 minutos desde el último abono.
  Si abonas o plantas a mano, usa **Reiniciar cuenta** (pestaña Espera).
- **Pestaña Espera:** revisar o no la pantalla mientras espera, margen extra, minutos de cada planta y las órdenes
  **Cortar ahora** y **Reiniciar cuenta** (solo funcionan con el programa en marcha).
- **Pestaña Sonido:** avisos con volumen ajustable.
- Cerrar la ventana **no detiene** el programa; usa **Detener**.
- Mientras corre una ráfaga **no muevas el mouse ni escribas**: si lo haces, espera y retoma solo.

## Si algo falla

- El registro (`audihacks.log`, pestaña Registro) anota todo lo que hace.
- Si se queda en una pantalla que no reconoce guarda una captura en `observacion/pantallas/`.
- Al caerse el servidor tarda unos minutos en volver a entrar; es normal.

## Calibración (si tu jardín se ve distinto)

Las posiciones (parcelas, herramientas, botones) están en `config.json` y son para una ventana de 1024×768
vista desde el mismo lado. Si el jardín de la otra persona se ve de otro lado o con otro tamaño, hay que ajustar
`parcelas`, `herramientas`, `semillas` y las posiciones de `reingreso`. Las imágenes de `referencias/` sirven para
reconocer las pantallas; algunas pueden necesitar volver a guardarse con la pantalla de esa persona.

## Privacidad

Tus datos **no se suben**: la cuenta (`cuenta.dat`), los ajustes (`ajustes.json`), el sonido (`sonido.json`),
el registro y las capturas están en `.gitignore`.

## Aviso

Automatizar el juego puede ir contra sus normas. Úsalo bajo tu propio riesgo.
