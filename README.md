# Conga 9990 AI Spin Revolution — Home Assistant

Integración local experimental para la Cecotec Conga 9990 AI Spin Revolution.
Lee el estado y controla el robot por TCP/6668, y puede recibir mapas y rutas por
la LAN sin mantener abierta la aplicación oficial.

Este árbol contiene únicamente el componente de Home Assistant y documentación
saneada. No contiene APK, código de Cecotec/Thingclips, capturas de tráfico,
mapas domésticos, volcados de memoria, identificadores ni credenciales reales.

## Funciones

- Estado, batería, estadísticas, consumibles y ajustes expuestos como entidades.
- Inicio, pausa, parada, regreso a base, potencia, agua y patrón de limpieza.
- Mapa y posición durante la actividad del robot.
- Limpieza completa, puntual, por zonas y por habitaciones.
- Joystick de movimiento breve con parada explícita.
- Perfiles de limpieza almacenados en Home Assistant.
- Segmentos nativos, acciones para automatizaciones y frases españolas de Assist.
- Notificaciones persistentes de errores comunicados por el robot.

Las funciones físicas deben probarse con supervisión en cada instalación. La
posición solo se presenta como reciente cuando procede del canal activo y no ha
caducado; una ruta vacía no se convierte en una posición inventada.

## Instalación

1. Copia `custom_components/conga9990` a
   `/config/custom_components/conga9990`.
2. Reinicia Home Assistant.
3. Abre **Ajustes → Dispositivos y servicios → Añadir integración**.
4. Busca **Conga 9990 Local** e introduce los datos de tu propio robot.

Para estado y control se necesitan:

- `host`: IP local del robot;
- `device_id`: identificador del dispositivo;
- `local_key`: clave local de 16 bytes.

Para mapa y posición se necesitan además:

- `map_owner_uid`: identidad del propietario en el canal P2P;
- `map_file_token`: credencial hexadecimal de 32 caracteres del canal de archivos.

No deben usarse los valores que la app muestra como **Dispositivo SN** o
**Módulo UUID**. Se comprobó sobre el mismo registro que `device_id` corresponde a
`devId`/`communicationId`, mientras que «Módulo UUID» corresponde al campo `uuid`
del SDK. `local_key` es otro campo independiente de 16 bytes. Ninguno de los dos
coincide con el SN o el UUID visible.

Home Assistant valida la conexión local antes de guardar la entrada. Si solo se
configuran los tres primeros campos, las entidades de control funcionan pero no
se inicia el receptor de mapas.

## Obtención de los datos

La aplicación no ofrece una pantalla para exportarlos. En el desarrollo original
se obtuvieron exclusivamente de una sesión autenticada del propietario:

1. La IP se identificó en la concesión DHCP del router/hotspot mediante la MAC
   del robot y se confirmó TCP/6668.
2. `device_id` y `local_key` son los campos `devId` y `localKey` del objeto
   `DeviceBean` que el SDK de Thingclips/Tuya carga en memoria al abrir el robot
   en la aplicación oficial, ejecutada en un emulador Android aislado con la
   sesión del propietario. El `devId` se identifica además por el nombre del
   subdirectorio que la app crea bajo la caché `ipc_sweeper_robot`. Se usaron dos
   vías para leerlos: (A) lectura del objeto JSON ya serializado en regiones de
   datos Dalvik no ejecutables del proceso, y (B) tras volver a vincular el
   Wi-Fi, lectura de los getters `getDevId()`/`getLocalKey()` del mismo objeto ya
   cargado por el SDK. La clave se validó contra una trama capturada y con una
   lectura de estado real. Ver [CREDENTIALS.md](docs/CREDENTIALS.md) para el
   procedimiento completo.
3. Al abrir la vista normal del mapa se observaron, sin modificarlos, los
   argumentos que el SDK Sweeper utiliza para negociar P2P y autenticarse ante el
   álbum fijo `ipc_sweeper_robot`. De ahí proceden `map_owner_uid` y la credencial
   de archivos de 32 caracteres.
4. Las credenciales se validaron primero con una lectura de estado y después con
   una solicitud limitada a `map.bin.stream`, `cleanPath.bin.stream` y
   `navPath.bin.stream`. No se solicitaron rutas arbitrarias, firmware ni shell.

El **decodificador del mapa** (el formato binario que esos ficheros usan, no una
credencial) se dedujo del fichero en reposo de la caché de la app y se validó
reconstruyéndolo byte a byte desde la captura P2P. El procedimiento está en
[IMPLEMENTATION.md, sección 4.1](docs/IMPLEMENTATION.md).

La contraseña ICE/TURN que puede aparecer en la configuración RTC es temporal y
no es `local_key` ni `map_file_token`. No debe guardarse como sustituto de ellas.

Consulta [Obtención y tratamiento de credenciales](docs/CREDENTIALS.md) y
[Procedimiento de implementación](docs/IMPLEMENTATION.md) para el detalle.

## Seguridad de las credenciales

- No publiques `.storage/core.config_entries`, diagnósticos sin revisar, PCAP,
  mapas, JSON de sesión ni scripts configurados con valores reales.
- Reserva la IP mediante DHCP, pero no incluyas la MAC en incidencias públicas.
- Protege las copias de seguridad de Home Assistant: contienen la entrada de la
  integración.
- Tras restablecer o volver a emparejar el robot, usa **Reconfigurar**; pueden
  cambiar `device_id`, `local_key` y `map_file_token`.
- Los diagnósticos propios del componente omiten credenciales, pero aun así deben
  revisarse antes de compartirlos.

## Procedencia y publicación

El cliente Home Assistant y los codificadores incluidos aquí son implementaciones
propias. La fase inicial se basó en tráfico y datos de sesión del dispositivo. Para completar mapa, zonas y navegación se usaron posteriormente
observación dinámica con Frida y la skill `reverse-engineer-anything`, además de
análisis estático acotado del panel y SDK oficiales.

Este proyecto ha usado Frida y REA, pero debería estar dentro de la legalidad debido a que se está dando compatibilidad a un dispositivo en un lugar donde no la tenía
## Estructura

```text
custom_components/conga9990/  Integración instalable
docs/CREDENTIALS.md           Procedencia y rotación de credenciales
docs/IMPLEMENTATION.md        Integración del protocolo en Home Assistant
```
