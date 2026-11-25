# Procedimiento de implementación en Home Assistant

## 1. Del estado local a un coordinador

El cliente de `protocol/local.py` abre TCP/6668, negocia una clave de sesión con
nonces y HMAC, valida las envolventes y descifra únicamente mensajes autenticados.
El coordinador consulta el estado periódicamente y conserva el último conjunto de
puntos de datos válido. Un fallo de red marca las entidades como no disponibles;
no fabrica valores.

La tabla saneada `profile.json` describe identificador, nombre, tipo, rango y modo
de los puntos de datos observados. Las plataformas `sensor`, `binary_sensor`,
`number`, `select`, `switch`, `button` y `vacuum` crean entidades solo cuando el
campo correspondiente existe o representa una acción explícita.

## 2. Flujo de configuración

`config_flow.py` solicita IP, identificador y clave local, ejecuta una lectura real
y exige los campos mínimos de estado y batería antes de crear la entrada. Las dos
credenciales de mapa son opcionales, pero deben proporcionarse juntas y cumplir
su formato. La reconfiguración vuelve a validar antes de recargar la integración.

La identidad del registro de entidades puede conservarse cuando el mismo robot se
vuelve a emparejar y cambia su identificador de protocolo. Esta migración debe
hacerse solo tras confirmar físicamente que sigue siendo el mismo dispositivo.

## 3. Entidad aspiradora y acciones

`vacuum.py` traduce estados del protocolo a las actividades nativas de Home
Assistant y expone únicamente capacidades respaldadas por el mapa o el perfil.
Las acciones adicionales se registran como servicios de entidad con validación de
esquema. Coordenadas, número de zonas, duración manual y repeticiones tienen
límites antes de codificarse.

El movimiento manual se envía en intervalos breves. Al soltar el control, perder
el foco o cerrar la tarjeta se solicita parada. Esto reduce el riesgo de que una
sesión del navegador abandonada mantenga movimiento continuo.

## 4. Mapa, rutas y posición

El canal de mapas negocia una ruta P2P local autenticada y limita el servicio de
archivos al álbum `ipc_sweeper_robot` y a tres nombres conocidos:

- `map.bin.stream`;
- `cleanPath.bin.stream`;
- `navPath.bin.stream`.

El receptor valida STUN, HMAC, cifrado, segmentos KCP, tamaños, estructura del
mapa y límites de coordenadas. No ofrece una API de ruta arbitraria.

El flujo se abre solo cuando el estado del robot indica limpieza, mapeo,
desplazamiento, regreso o control manual. Se cancela al quedar inactivo, pausado,
cargando o averiado. Una ruta vacía elimina la posición reciente en vez de dibujar
el origen del mapa. Las rutas de navegación previstas tampoco se presentan como
posición medida.

### 4.1 Cómo se obtuvo el decodificador del mapa

El decodificador (`protocol/map.py`, `protocol/lz4_block.py`,
`protocol/map_stream.py`, `protocol/p2p.py`, `protocol/path.py`) es código propio
derivado del **comportamiento observado**, no portado de la app ni del SDK. Se
obtuvo en dos fases, ambas sobre datos del robot del propietario.

**Fase 1 — perfil del fichero en reposo.** La app oficial, al mostrar el mapa,
deja una copia en su caché normal bajo el álbum `ipc_sweeper_robot`, en los
ficheros `map.bin.stream`, `cleanPath.bin.stream` y `navPath.bin.stream`. Se leyó
una de esas copias (1689 bytes en la muestra) y se dedujo su estructura inspeccionando
los bytes, sin desensamblar código:

- byte 0: versión del perfil (valor observado `2`);
- offset 5: ancho de la rejilla como entero de 16 bits *little endian* (93 en la
  muestra);
- offset 24: un bloque **LZ4** sin cabecera de framing propia;
- al descomprimir, 11999 bytes, de los que los dos últimos son `01 00`;
- los 11997 restantes son la rejilla de 93 × 129 celdas, con valores
  `E0` = fondo, `E7` = suelo y `F1` = borde.

El inflador LZ4 se escribió desde el [formato público de bloques LZ4](https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md),
con límites de tamaño y comprobación de offsets; no incorpora código de LZ4, de
Cecotec ni una extensión C. El decodificador rechaza versiones, valores o
metadatos distintos de los observados, y la imagen se genera desde las celdas.
El significado del resto de campos (escala física, coordenadas, habitaciones,
posición) no está determinado y no se inventa.

**Fase 2 — reconstrucción desde la captura P2P (validación).** Para confirmar que
el mismo fichero llega por la LAN, se descifró la señalización del robot capturada
(comando 32) usando la sesión local ya verificada. De esa señalización se separó:

- un SDP con transporte `AES/KCP` y una clave de sesión de 16 bytes
  (`a=aes-key` en hexadecimal);
- el perfil UDP: cabecera **KCP** *little endian* de 24 bytes, cuerpo y
  **HMAC-SHA1** de 20 bytes. El HMAC cubre cabecera y cuerpo con esa misma clave y
  se verifica **antes** de descifrar;
- el cuerpo: IV de 16 bytes y **AES-CBC** con relleno PKCS7; los ACK observados
  tienen cuerpo vacío.

Ordenados los datagramas por número de secuencia, el servicio de archivos entrega
cabeceras de fichero de 80 bytes seguidas de los fragmentos. Con ello se
reconstruyó el primer mapa completo (1200 + 489 bytes) y se comprobó **igualdad
byte a byte** con la copia de caché de 1689 bytes. Esa coincidencia exacta es la
que valida el decodificador: lo que llega por P2P es el mismo `map.bin.stream` que
la Fase 1 ya sabía interpretar.

Toda la observación fue pasiva (descifrado y verificación de capturas propias). No
se envió tráfico P2P fabricado, no se usó código de la app ni se solicitaron rutas
distintas de los tres nombres conocidos. Los ficheros `.bin.stream`, las capturas y
las claves son privados y no se distribuyen con este árbol.

## 5. Imagen y tarjeta de Lovelace

La plataforma `image` publica el PNG del mapa y metadatos calibrados: dimensiones,
habitaciones, posición, origen, antigüedad y perfiles. `conga-map-card.js` se sirve
como recurso local, sin dependencias externas, y separa mapa, control,
habitaciones y perfiles en secciones reutilizables.

El usuario debe confirmar una selección antes de que se envíe una orden. Los
perfiles se almacenan en Home Assistant y se vinculan al identificador/calibración
del mapa para evitar ejecutarlos accidentalmente sobre otro plano.

## 6. Errores y diagnósticos

Los códigos de avería conocidos producen una notificación persistente por robot.
El mismo código actualiza la notificación en vez de duplicarla y solo se retira
cuando el robot comunica que la avería ha desaparecido. Una desconexión no se
interpreta como resolución.

`diagnostics.py` informa de cobertura del esquema y estado de las capacidades sin
incluir IP, identificadores, claves ni tokens.

## 7. Instalación empleada

El despliegue original siguió un proceso recuperable:

1. crear un archivo solo con `custom_components/conga9990`;
2. validar `manifest.json` y el dominio en un directorio temporal;
3. detener Home Assistant;
4. guardar copia de la integración y de su entrada de configuración;
5. sustituir el directorio de forma atómica;
6. iniciar Home Assistant y comprobar carga, entidades y recursos estáticos;
7. conservar la copia para una reversión manual.

Para una instalación nueva no es necesario modificar `.storage`: se debe usar el
flujo gráfico normal. La edición directa solo se utilizó en el laboratorio para
preservar entidades durante una revinculación confirmada y no se recomienda como
procedimiento general.

## 8. Procedencia técnica

El protocolo de control se reconstruyó a partir de tráfico autenticado y datos de
sesión del robot del propietario. El mapa y las órdenes combinadas requirieron una
fase posterior con observación dinámica de la aplicación oficial, Frida, análisis
estático acotado y la skill `reverse-engineer-anything`. El método concreto con el
que se dedujo y validó el formato de mapa se detalla en la sección 4.1. Los cuerpos
y artefactos originales no están en esta distribución.

El componente contiene código propio y validaciones derivadas del comportamiento
observado, pero el proceso completo no fue una separación clean-room formal. Esta
declaración de procedencia debe conservarse si se redistribuye el árbol.
