# Obtención y tratamiento de credenciales

## Alcance

El procedimiento se realizó sobre el robot y la cuenta del propietario. No se
probaron cuentas o dispositivos ajenos, fuerza bruta, bypass de autenticación ni
explotación del robot. Los valores reales se conservaron fuera de este árbol.

## Campos

| Campo | Formato observado | Uso |
| --- | --- | --- |
| `host` | IPv4 o nombre resoluble | Conexión LAN al robot |
| `device_id` | Identificador alfanumérico | Identidad de protocolo y destino P2P |
| `local_key` | 16 bytes | Autenticación y cifrado del protocolo local |
| `map_owner_uid` | Identificador alfanumérico | Origen de la oferta P2P de mapas |
| `map_file_token` | 32 caracteres hexadecimales | Autenticación del servicio de archivos |

### Campos visibles que no sirven como sustitutos

La pantalla de información de la app muestra **Dispositivo SN** y **Módulo
UUID**, pero no son `device_id` ni `local_key`. La verificación cruzada del objeto
del SDK y el bloque de información comunicado por el robot dio estas relaciones,
sin depender de que los textos tengan una longitud parecida:

| Etiqueta/campo | Relación comprobada |
| --- | --- |
| `device_id` | `devId`, igual a `communicationId` |
| `local_key` | `localKey`, clave independiente de 16 bytes |
| Dispositivo SN | `Device_SN`, distinto de los dos anteriores |
| Módulo UUID | `Module_UUID`, igual al campo `uuid` del SDK y distinto de los dos anteriores |

Por tanto, copiar SN y UUID desde la pantalla de la app no permite autenticar la
integración. Se necesitan los campos internos de la sesión autorizada descritos a
continuación.

## Procedimiento utilizado

### Dirección local

Se conectó la Conga a un hotspot administrado por el propietario y se consultó su
concesión DHCP. La asociación se hizo con la MAC visible en el propio entorno. Se
confirmó de forma independiente que el robot aceptaba conexiones en TCP/6668.

Para una instalación normal basta con consultar la lista de clientes del router
y crear una reserva DHCP. No es necesario configurar el robot con una IP pública
ni exponer TCP/6668 fuera de la red doméstica.

### Identidad y clave local

Ambos valores son campos internos del `DeviceBean` que el SDK de
Thingclips/Tuya carga en memoria cuando la app abre el robot. No aparecen en
ninguna pantalla exportable. La correspondencia es directa:

- `device_id` = campo `devId` del `DeviceBean` (igual a `communicationId`);
- `local_key` = campo `localKey` del `DeviceBean`, una cadena de 16 caracteres
  ASCII que el protocolo local usa tal cual como clave AES-128.

Preparación común (realizada una sola vez):

1. Ejecutar la APK oficial sin modificar en un emulador Android aislado con root
   (`adb root` devuelve UID 0; `getprop ro.boot.qemu` devuelve `1`).
2. Iniciar sesión con la cuenta del propietario, abrir el robot y entrar una vez
   en la vista de mapa, para que el SDK cargue el `DeviceBean` y cree su caché.
3. Averiguar el `devId` sin leer memoria todavía: la app crea un subdirectorio
   por dispositivo bajo la caché del álbum fijo `ipc_sweeper_robot`, y el nombre
   del subdirectorio es el propio `devId`:

   ```sh
   adb -s emulator-5556 shell find \
     /data/user/0/es.cecotec.forceclima/cache/ipc_sweeper_robot \
     -mindepth 1 -maxdepth 1 -type d
   ```

Se emplearon dos vías para leer la pareja `devId`/`localKey`. Las dos leen el
mismo objeto ya cargado por el SDK; ninguna descompila, parchea ni fuerza nada.

#### Vía A — lectura del objeto en memoria Dalvik (extracción inicial)

Un programa propio localiza el `DeviceBean` ya serializado como JSON dentro del
montón administrado del proceso oficial. Sus restricciones:

- solo acepta un destino `emulator-*` y comprueba que es QEMU y tiene root;
- resuelve el PID con `pidof es.cecotec.forceclima` y lee `/proc/<pid>/maps`;
- solo lee regiones de **datos** `rw` sin permiso de ejecución cuyo nombre sea
  `[anon:dalvik-main space]` (acotada, p. ej. a 256 MiB) o
  `[anon:dalvik-large object space allocation]`; nunca regiones ejecutables,
  bibliotecas ni código;
- las copia por bloques con `dd if=/proc/<pid>/mem`, busca la etiqueta
  `"localKey":`, retrocede hasta la llave `{` que la enmarca y decodifica solo
  JSON válido;
- guarda el objeto únicamente si contiene el `devId` o el `name` del robot
  seleccionado, en un fichero privado nuevo con modo 0600, sin imprimir la clave.

El objeto recuperado es el `DeviceBean` completo (`devId`, `localKey`, `devKey`,
`uuid`, `ip`, `mac`, `name`, `productId`, `communicationId`…). De él se toman
`device_id` = `devId` y `local_key` = `localKey`.

#### Vía B — getters del SDK en ejecución (tras volver a vincular)

Al volver a vincular el Wi-Fi, la clave almacenada caducó: la conexión local se
cerraba (`IncompleteReadError`) y la vía A ya no encontraba ningún registro
coincidente. Se leyeron entonces los getters del mismo objeto que el SDK ya
tenía cargado, mediante observación dinámica (Frida) sobre el proceso de la app,
sin alterar llamadas ni respuestas. El fragmento esencial fue:

```js
// device = ThingHomeSdk.getDataInstance().getDeviceBean(devId)
send({
  device_id: String(device.getDevId()),
  local_key: String(device.getLocalKey()),
  ip:        String(device.getIp()),
});
```

El resultado mantuvo el mismo `device_id` y entregó una `local_key` nueva de 16
bytes. (Nota: `getIp()` devuelve la IP pública/WAN del registro en la nube, no
sirve como `host`; este se obtiene del DHCP de la red local, ver arriba.)

#### Validación de la clave

La `local_key` se comprobó de dos formas independientes antes de darla por buena:

- Contra una trama TCP/6668 capturada del propio robot. Las tramas del protocolo
  empiezan por `00 00 66 99`; el intercambio inicial se descifra y autentica con
  `AES-GCM`, tomando como nonce los bytes 18–30 y como datos autenticados (AAD)
  la cabecera (bytes 4–18). Si la autenticación cuadra, la clave es correcta.
- Con una lectura de estado real del robot: la clave válida devolvió el conjunto
  de puntos de datos (batería, estado, etc.); una clave distinta
  (`0000000000000000`) se usó como control negativo y fue rechazada.

### Lo que no sirve: las preferencias cifradas de la sesión

Se descifraron también las preferencias de la propia sesión protegidas por la
Keystore de Android (AES-GCM, alias de clave de la app). Contenían datos de la
cuenta (`uid`, `sid`, `ecode`, perfil y una `GLOBAL_SECURITY_KEY`), pero **no**
`localKey` ni `devId`. Por tanto, esa vía no permite obtener las credenciales de
la integración y no debe usarse como atajo.

### Cuenta y credencial de mapas

Al abrir la vista de mapa, la aplicación llama a su SDK Sweeper/P2P. Se observaron
los argumentos y respuestas originales sin sustituirlos ni bloquearlos. La cadena
de llamadas permitió separar:

- la identidad del propietario que figura como origen de la negociación;
- la credencial estable usada en la autorización del servicio de archivos;
- las credenciales temporales ICE/TURN utilizadas para conectividad NAT;
- las claves efímeras que protegen cada sesión de transporte.

Solo las dos primeras se guardan como `map_owner_uid` y `map_file_token`. Las
credenciales RTC temporales no forman parte de la configuración persistente.

## Almacenamiento en Home Assistant

Los cinco campos se almacenan en la entrada de configuración de Home Assistant.
El formulario muestra las claves como contraseñas. El componente no las añade a
sus atributos de entidad ni a su salida de diagnóstico.

La configuración debe tratarse como un secreto:

- permisos restringidos en `/config/.storage`;
- copias de seguridad cifradas o almacenadas en un destino de confianza;
- nada de valores reales en YAML público, incidencias o capturas de pantalla;
- reconfiguración después de un reset, cambio de cuenta o emparejamiento.

Este repositorio no incluye una herramienta de extracción automática: una
herramienta así tendría que adaptarse a versiones concretas de la aplicación y
procesaría secretos de cuenta. La documentación conserva el método y sus límites
sin distribuir sesiones ni instrumentación configurada.
