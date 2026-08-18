# Consideraciones legales y de cumplimiento

> ⚠️ **Esto NO es asesoría legal.** Es una guía operativa para reducir riesgos
> al vender o desplegar este software. Antes de ofrecerlo comercialmente hacé
> revisar este documento (y el contrato de licencia/servicio) por un abogado
> con el que estés dispuesto a litigar en tu jurisdicción.

## 1. Qué hace este software

Extrae productos inactivos de la tienda PrestaShop del cliente, busca
información (fichas técnicas, descripciones, imágenes) en sitios web públicos
(scrapeo con Selenium, DuckDuckGo, PDFs) y la propone/escribe de vuelta en la
tienda. **El scrapeo de terceros y la republicación de contenido son las dos
áreas con mayor exposición legal.**

## 2. Cumplimiento en el scraping (fuentes)

- Respetá los **términos de servicio** de cada sitio de origen. Un sitio que
  prohíba el scrapeo no debe estar en `brands_mapping.json`.
- Respetá `robots.txt`, el `API_SLEEP` (throttle) y los límites de velocidad
  del sitio. Este proyecto ya aplica throttling; no lo reduzcas para "acelerar".
- El contenido de sitios de **afiliados/resellers** (no fabricantes) es el de
  mayor riesgo: suele tener licencias restrictivas y contenido con copyright.
- Antes de agregar una marca/sitio nuevo a `brands_mapping.json`, documentá:
  quién es el titular, si permite el acceso automatizado y para qué uso.
- **Uso transitorio:** descargar una página para extraer datos puntuales es
  distinto a republicar ese contenido. Extraer no te da derecho a publicarlo.

## 3. Derechos de contenido (fotos, fichas técnicas, marcas)

- **Imágenes, descripciones y fichas técnicas tienen copyright** de sus
  titulares (fabricante, importador o distribuidor). Scrapearlas y publicarlas
  en la tienda de un cliente puede constituir infracción si el cliente no tiene
  licencia.
- **El cliente (tienda) es responsable** de tener los derechos para publicar
  el contenido. El proveedor de este software no es autor ni publicador del
  contenido; solo lo copia y sugiere.
- **Marcas:** el uso de nombres de marca (Samsung, TCL, Acer, etc.) para
  identificar productos suele ser uso nominativo legítimo. No los uses de
  forma que sugiera patrocinio o afiliación.
- **Verificación de derechos:** en el onboarding del cliente, pedile confirmar
  que cuenta con autorización (contrato de distribución/importación) para
  publicar las marcas y los datos que procesa.

## 4. Responsabilidad por el contenido publicado

- El contenido es **generado/copilado automáticamente** (scrapeo + plantillas
  + traducción automática). Puede contener errores (características, medidas,
  modelos). El cliente es quien lo aprueba y publica.
- Consumidor final: en muchas jurisdicciones las descripciones engañosas o
  erróneas generan responsabilidad frente al consumidor (ej. lealtad comercial
  en Argentina, leyes de consumidor en UE/España). Es responsabilidad del
  cliente validar los datos antes de activar un producto.
- El software **no debe usarse** para manipular precios, stock, reseñas o
  disponibilidad de forma engañosa.

## 5. Protección de datos y claves

- **API keys de PrestaShop:** son credenciales del cliente. No las compartas,
  no las subas al repositorio (`.env` está gitignoreado), transmittilas por
  canales seguros y limitá los permisos del webservice a lo mínimo necesario.
- **Datos del cliente y de su tienda:** el operador (vos) es procesador; el
  cliente es controlador. Si operás un servicio multi-cliente, definí por
  contrato quién es controlador y quién procesador, y aplicá las medidas
  mínimas (acceso restringido, cifrado en tránsito, política de retención).
- **Logs de auditoría:** `audit_log` guarda "actor" de cada acción. Limitalo a
  identificar quién operó (usuario interno), no datos personales de terceros.
- Si procesás datos de personas en la UE/España, aplicá GDPR; en Argentina,
  Ley 25.326. No almacenes más datos de los necesarios.

## 6. Cláusulas recomendadas para el contrato con tus clientes

1. **Licencia de uso** del software (qué hace, cómo, y que el cliente no lo
   revenda ni lo use contra fuentes que lo prohíban).
2. **Responsabilidad por contenido:** el cliente declara que tiene los
   derechos de publicación (marcas, imágenes, fichas) y que es responsable de
   aprobar y validar lo que se publique.
3. **Cumplimiento del scrapeo:** el cliente acepta que el uso se limita a
   fuentes permitidas y que no modificará los límites de velocidad.
4. **Datos:** tratamiento de datos personales (clave API, datos de tienda),
   medidas de seguridad y notificación de incidentes.
5. **Exclusión de garantías:** software "tal cual", sin garantía de resultados,
   disponibilidad del sitio de origen o exactitud del contenido.
6. **Limitación de responsabilidad:** el proveedor no responde por daños
   indirectos ni por contenido publicado por el cliente.
7. **Propiedad intelectual:** todo el código, configuraciones y documentación
   son del proveedor; los datos del cliente son del cliente.

## 7. Checklist operativo (antes de vender/desplegar)

- [ ] Revisar `brands_mapping.json` y confirmar que solo hay fuentes permitidas.
- [ ] Contrato con el cliente firmado (cláusulas de la sección 6).
- [ ] Confirmación del cliente de que tiene derechos para publicar el contenido.
- [ ] API key del webservice con permisos mínimos y canal seguro de entrega.
- [ ] No subir `.env`, claves ni datos de clientes al repositorio.
- [ ] Definir política de retención/borrado de datos del cliente al finalizar.
- [ ] Revisión legal local (Argentina / país del cliente) antes del primer contrato.

## 8. Restricciones de uso

Este software está prohibido para:

- Scrapear sitios que prohíban el acceso automatizado o la republicación.
- Publicar contenido (imágenes, textos, fichas) sin los derechos correspondientes.
- Actividades fraudulentas, engañosas o que violen leyes de consumo.
- Procesar datos personales sensibles o fuera del marco contractual.
