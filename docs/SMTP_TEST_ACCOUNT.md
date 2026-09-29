# Cuenta técnica de correo para pruebas

La cuenta de Gmail de Psycode para integración SMTP está **pendiente de creación por el equipo**. Ninguna dirección referencial en este repositorio representa una cuenta creada. La persona responsable debe designarse en el gestor interno de accesos del equipo; no usar una cuenta personal. La información de recuperación (correo o teléfono) debe ser administrada por el equipo.

Pasos para el administrador designado:

1. Crear una cuenta cuyo nombre identifique a Psycode y su uso exclusivo para pruebas de envío. Registrar titularidad, custodio y mecanismo de recuperación en el gestor interno de accesos.
2. Activar verificación en dos pasos. Si Google permite [contraseñas de aplicación](https://support.google.com/accounts/answer/185833), generar una exclusiva para Psycode. Si no lo permite y el equipo usa Google Workspace, el administrador puede habilitar su [relay SMTP autorizado](https://support.google.com/a/answer/176600) y configurar su host y autenticación según la política institucional. Para una cuenta Gmail sin contraseña de aplicación ni relay autorizado, la integración SMTP queda pendiente. Nunca configurar la contraseña normal de la cuenta en Psycode.
3. Guardar dirección y credencial únicamente como secretos del ambiente de ejecución. Configurar `EMAIL_BACKEND=smtp`, `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true`, `SMTP_USERNAME`, `SMTP_PASSWORD` y `EMAIL_FROM` con la dirección técnica. No copiar los valores a Git, Jira, documentación, registros ni capturas.
4. Ejecutar una prueba de integración desde el ambiente de pruebas hacia un buzón del equipo, solicitando recuperación para una cuenta sintética existente. Comprobar recepción, enlace y confirmación. Mantener `EMAIL_TIMEOUT_SECONDS` configurado.
5. Para revocar, quitar la contraseña de aplicación desde la seguridad de la cuenta de Google y retirar el secreto del ambiente. Para renovar, generar una nueva credencial autorizada, actualizar el secreto y repetir la prueba. Registrar la rotación en el gestor interno sin guardar el valor de la credencial.

**Dependencia del cliente:** remitente o relay institucional definitivo, credenciales y política de envío. Al recibirlos, sustituir las variables SMTP y retirar la cuenta de pruebas del ambiente; no requiere cambios de código.
