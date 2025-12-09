# VotaciónApp - Sistema de Votación con Blockchain

Sistema de votación electrónica seguro y transparente que utiliza blockchain (Polygon Amoy Testnet) para garantizar la integridad de los votos.

## 🚀 Características

- **Autenticación dual**: Sistema de login separado para administradores y votantes
- **Blockchain Integration**: Registro de votos en Polygon Amoy Testnet
- **Gestión de eventos**: Crear y administrar múltiples eventos de votación
- **Asignación flexible**: Asignar participantes y candidatos por evento
- **Resultados en tiempo real**: Visualización de estadísticas y resultados
- **Envío de credenciales**: Sistema de email automático con Gmail SMTP
- **Interfaz moderna**: UI con Tailwind CSS y Bootstrap Icons

## 📋 Requisitos Previos

- Python 3.14+
- MySQL 8.0+
- Redis (para Celery)
- Node.js (opcional, para desarrollo frontend)
- Cuenta de Gmail con contraseña de aplicación
- Wallet de Polygon Amoy con MATIC para gas

## 🔧 Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/Ayax111-debug/votacion_blockchain.git
cd votacion_blockchain
```

### 2. Crear y activar entorno virtual

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar base de datos

Crear base de datos MySQL:

```sql
CREATE DATABASE votacion_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'votacion_user'@'localhost' IDENTIFIED BY 'tu_contraseña';
GRANT ALL PRIVILEGES ON votacion_db.* TO 'votacion_user'@'localhost';
FLUSH PRIVILEGES;
```

### 5. Configurar variables de entorno

Crear archivo `.env` en la raíz del proyecto:

```env
# Base de datos
DB_NAME=votacion_db
DB_USER=votacion_user
DB_PASSWORD=tu_contraseña
DB_HOST=localhost
DB_PORT=3306

# Email (Gmail)
EMAIL_HOST_USER=tu_email@gmail.com
EMAIL_HOST_PASSWORD=tu_app_password_de_gmail

# Blockchain
POLYGON_RPC_URL=https://rpc-amoy.polygon.technology
WALLET_PRIVATE_KEY=tu_clave_privada
CONTRACT_ADDRESS=0x64a11B612dF868f8680523494A6b6c1743dfd44a

# Django
SECRET_KEY=tu-secret-key-aqui
DEBUG=True
```

### 6. Aplicar migraciones

```bash
python manage.py migrate
```

### 7. Crear superusuario

```bash
python manage.py createsuperuser
```

### 8. Ejecutar script de inicialización (opcional)

Si tienes votos existentes y necesitas poblar la tabla de resultados:

```bash
python recalcular_resultados.py
```

## 🎯 Uso

### Iniciar el servidor

```bash
python manage.py runserver
```

La aplicación estará disponible en: `http://127.0.0.1:8000`

### Iniciar Celery (para tareas asíncronas)

```bash
# Worker
celery -A votacion worker -l info

# Beat (tareas programadas)
celery -A votacion beat -l info
```

## 👥 Roles y Accesos

### Administrador
- URL: `/login/`
- Funciones:
  - Crear y gestionar eventos
  - Asignar participantes y candidatos
  - Ver estadísticas en tiempo real
  - Crear usuarios votantes
  - Desactivar/activar eventos

### Votante
- URL: `/login-votante/`
- Funciones:
  - Ver eventos asignados
  - Emitir votos
  - Ver historial de votaciones
  - Ver resultados de eventos finalizados

## 📊 Estructura del Proyecto

```
votacion_blockchain/
├── elecciones/              # App principal
│   ├── models.py           # Modelos de BD
│   ├── views.py            # Lógica de vistas
│   ├── forms.py            # Formularios Django
│   ├── web3_utils.py       # Integración blockchain
│   ├── templates/          # Templates HTML
│   └── migrations/         # Migraciones de BD
├── votacion/               # Configuración del proyecto
│   ├── settings.py         # Configuración Django
│   ├── urls.py             # Rutas principales
│   └── celery.py           # Configuración Celery
├── contracts/              # Smart Contracts
├── media/                  # Archivos subidos
├── static/                 # Archivos estáticos
├── requirements.txt        # Dependencias Python
└── manage.py              # CLI de Django
```

## 🔐 Configuración de Email

Para enviar credenciales automáticamente:

1. Habilita la verificación en 2 pasos en tu cuenta de Gmail
2. Genera una contraseña de aplicación en: https://myaccount.google.com/apppasswords
3. Configura las variables en `.env` o `settings.py`:

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'tu_email@gmail.com'
EMAIL_HOST_PASSWORD = 'tu_app_password'
DEFAULT_FROM_EMAIL = 'VotaciónApp <tu_email@gmail.com>'
```

## ⛓️ Configuración Blockchain

### Smart Contract
- Red: Polygon Amoy Testnet
- Contrato: `0x64a11B612dF868f8680523494A6b6c1743dfd44a`
- Wallet: `0xa26E03bAa5dc37Dd5F75612d916182856e7f0875`

### Obtener MATIC de prueba
1. Visita: https://faucet.polygon.technology/
2. Selecciona "Amoy Testnet"
3. Ingresa tu dirección de wallet
4. Solicita tokens (0.1 MATIC por día)

### Verificar transacciones
https://amoy.polygonscan.com/address/0xa26E03bAa5dc37Dd5F75612d916182856e7f0875

## 📦 Dependencias Principales

- **Django 6.0**: Framework web
- **web3.py 7.14.0**: Integración con blockchain
- **PyMySQL 1.1.2**: Conector MySQL
- **Celery 5.6.0**: Tareas asíncronas
- **Redis 5.0.0**: Broker para Celery
- **python-dotenv 1.2.1**: Variables de entorno
- **Pillow 11.0.0**: Procesamiento de imágenes

Ver `requirements.txt` para la lista completa.

## 🛠️ Scripts Útiles

### Recalcular resultados
```bash
python recalcular_resultados.py
```

### Limpiar votos fallidos
```bash
python limpiar_votos_fallidos.py
```

### Verificar flujo de votos
```bash
python scripts/check_vote_flow.py
```

## 🐛 Solución de Problemas

### Error: "No module named 'django'"
```bash
# Asegúrate de activar el entorno virtual
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
```

### Error de conexión a MySQL
```bash
# Verifica que MySQL esté corriendo
mysql -u votacion_user -p votacion_db
```

### Error de blockchain
```bash
# Verifica tu balance de MATIC
# Asegúrate de tener al menos 0.01 MATIC
```

### Votos duplicados en resultados
```bash
# Ejecuta el script de recálculo
python recalcular_resultados.py
```

## 📝 Flujo de Votación

1. **Admin crea evento** con fechas de inicio y término
2. **Admin asigna participantes** (votantes habilitados)
3. **Admin asigna candidatos** (opciones de voto)
4. **Votante inicia sesión** con RUT y clave
5. **Votante selecciona candidato** y confirma
6. **Sistema genera commitment** único
7. **Commitment se envía a blockchain** (Polygon Amoy)
8. **Si blockchain confirma**, se guarda en BD
9. **Tabla Resultado se actualiza** automáticamente
10. **Resultados visibles** cuando evento termina

## 🔒 Seguridad

- Votos registrados en blockchain inmutable
- Commitments únicos por votante
- Verificación de participación antes de votar
- Prevención de doble voto
- Contraseñas hasheadas
- CSRF protection habilitado
- Validación de sesiones

## 📈 Características Futuras

- [ ] Verificación de votos por QR
- [ ] Dashboard con gráficos interactivos
- [ ] Exportación de resultados a PDF
- [ ] Sistema de notificaciones push
- [ ] Integración con otras blockchains
- [ ] API REST para integraciones
- [ ] App móvil

## 👨‍💻 Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Ver `LICENSE` para más detalles.

## 📧 Contacto

- GitHub: [@Ayax111-debug](https://github.com/Ayax111-debug)
- Proyecto: [votacion_blockchain](https://github.com/Ayax111-debug/votacion_blockchain)

## 🙏 Agradecimientos

- Polygon para la infraestructura blockchain
- Django community
- Bootstrap Icons
- Tailwind CSS

---

⭐ Si te gusta este proyecto, dale una estrella en GitHub!
