# 🚀 Docker Auto-Heal Service - Complete Application

## 📦 What You Have

A **fully functional, production-ready** Docker container auto-healing service built in Python with:

✅ **Core Monitoring Engine** - Monitors containers 24/7, auto-restarts on failures
✅ **Web UI Dashboard** - Modern, responsive interface to manage everything
✅ **REST API** - Full programmatic access with interactive documentation
✅ **Custom Health Checks** - HTTP, TCP, Exec, and Docker native support
✅ **Smart Restart Logic** - Cooldowns, backoffs, quarantine for flapping containers
✅ **Configuration Management** - In-memory state with JSON export/import
✅ **Event Logging** - Track all auto-heal actions and decisions
✅ **Prometheus Metrics** - Built-in observability

## 📁 Complete File Structure

```
docker-autoheal/
│
├── 🐍 Python Application
│   ├── main.py              # Entry point, service orchestration
│   ├── api.py               # FastAPI REST endpoints
│   ├── config.py            # Configuration management (thread-safe)
│   ├── docker_client.py     # Docker SDK wrapper
│   └── monitor.py           # Core monitoring engine
│
├── 🌐 Web Interface
│   └── static/
│       ├── index.html       # Bootstrap 5 UI
│       └── app.js           # JavaScript functionality
│
├── 🐳 Docker Deployment
│   ├── Dockerfile           # Container image definition
│   ├── docker-compose.yml   # Production deployment
│   └── docker-compose.test.yml  # Test environment with samples
│
├── 📚 Documentation
│   ├── README.md            # Full documentation (comprehensive)
│   ├── QUICKSTART.md        # 5-minute setup guide
│   ├── IMPLEMENTATION.md    # Technical implementation details
│   └── config-example.json  # Example configuration
│
├── 🧪 Testing & Demo
│   └── demo.py              # Interactive demo script
│
└── ⚙️ Configuration
    ├── requirements.txt     # Python dependencies
    ├── .gitignore          # Git exclusions
    └── .dockerignore       # Docker build exclusions
```

## 🎯 Key Features at a Glance

### 1️⃣ Automatic Container Healing
- Detects container failures (non-zero exit codes)
- Monitors health check status (unhealthy → restart)
- Configurable restart policies and modes
- Respects manual stops and restart policies

### 2️⃣ Smart Restart Management
- **Cooldown Periods**: Wait between restart attempts
- **Exponential Backoff**: Increasing delays for repeated failures
- **Restart Thresholds**: Max restarts within time window
- **Quarantine System**: Stop auto-healing flapping containers

### 3️⃣ Flexible Monitoring
- **Label-Based**: Monitor containers with `autoheal=true` label
- **UI Selection**: Enable/disable per container via web interface
- **Whitelist/Blacklist**: Filter by names or labels
- **Include All Mode**: Monitor all containers

### 4️⃣ Custom Health Checks
- **HTTP**: Check endpoints for expected status codes
- **TCP**: Test port connectivity
- **Exec**: Run commands inside containers
- **Docker Native**: Use Docker's built-in HEALTHCHECK

### 5️⃣ Web Management UI
- **Dashboard**: Real-time metrics and status
- **Container List**: View all containers, their status, health
- **Event Log**: History of auto-heal actions
- **Configuration**: Change all settings without restart
- **Export/Import**: Backup and restore configurations

### 6️⃣ REST API
- Full CRUD operations for containers
- Configuration management endpoints
- Health check definitions
- Event log access
- Interactive docs at `/docs`

## 🏃 Quick Start Commands

### Start the Service
```bash
# Using Docker Compose (recommended)
docker-compose up -d

# View logs
docker logs -f docker-autoheal

# Stop service
docker-compose down
```

### Access the Application
```bash
# Web UI
http://localhost:3131

# API Documentation
http://localhost:3131/docs

# Prometheus Metrics
http://localhost:9090/metrics

# Health Check
curl http://localhost:3131/health
```

### Run Demo
```bash
# Automated demo
python demo.py

# Interactive demo
python demo.py --interactive
```

### Test with Sample Containers
```bash
# Start full test environment
docker-compose -f docker-compose.test.yml up -d

# This starts:
# - autoheal service
# - 5 test containers (healthy nginx, failing container, HTTP test, Redis, unmonitored)

# Watch auto-heal in action
docker logs -f docker-autoheal
```

## 🎨 Web UI Tabs

### 📊 Dashboard (Top Metrics)
- Total Containers
- Monitored Containers
- Quarantined Containers
- Service Status

### 🗂️ Containers Tab
- List all running containers
- Enable/disable auto-heal (checkbox selection)
- Manual restart buttons
- Add custom health checks
- Unquarantine containers
- View container details

### 📜 Events Tab
- View last 50 auto-heal events
- See restart attempts and outcomes
- Track quarantine actions
- Timestamps and messages

### ⚙️ Configuration Tab
- **Monitor Settings**
  - Interval (how often to check)
  - Label filters
  - Include all mode

- **Restart Policy**
  - Mode (on-failure / health / both)
  - Cooldown seconds
  - Max restarts and window
  - Backoff settings

- **Export/Import**
  - Download config as JSON
  - Upload config from JSON

## 🔧 Configuration Examples

### Monitor All Containers
```json
{
  "monitor": {
    "interval_seconds": 30,
    "include_all": true
  }
}
```

### Aggressive Restart Policy
```json
{
  "restart": {
    "mode": "both",
    "cooldown_seconds": 10,
    "max_restarts": 5,
    "max_restarts_window_seconds": 300
  }
}
```

### Custom HTTP Health Check
```bash
# Via API
curl -X POST http://localhost:3131/api/healthchecks \
  -H "Content-Type: application/json" \
  -d '{
    "container_id": "my-container",
    "check_type": "http",
    "http_endpoint": "http://localhost:3131/health",
    "http_expected_status": 200,
    "interval_seconds": 30,
    "timeout_seconds": 10,
    "retries": 3
  }'
```

## 📊 API Endpoints Reference

### Status & Health
- `GET /health` - Service health check
- `GET /api/status` - System status with metrics

### Containers
- `GET /api/containers` - List all containers
- `GET /api/containers/{id}` - Get container details
- `POST /api/containers/select` - Enable/disable auto-heal
- `POST /api/containers/{id}/restart` - Manual restart
- `POST /api/containers/{id}/unquarantine` - Remove from quarantine

### Configuration
- `GET /api/config` - Get current config
- `PUT /api/config` - Update full config
- `PUT /api/config/monitor` - Update monitor settings
- `PUT /api/config/restart` - Update restart policy
- `GET /api/config/export` - Export as JSON
- `POST /api/config/import` - Import from JSON

### Health Checks
- `GET /api/healthchecks` - List all custom health checks
- `GET /api/healthchecks/{id}` - Get health check for container
- `POST /api/healthchecks` - Add custom health check
- `DELETE /api/healthchecks/{id}` - Remove health check

### Events
- `GET /api/events` - Get event log (last 50 events)
- `GET /api/events?limit=100` - Get specific number of events

## 🔍 Monitoring & Observability

### Prometheus Metrics
```bash
# View metrics
curl http://localhost:9090/metrics

# Metrics available:
# - autoheal_container_restarts_total
# - autoheal_containers_monitored
# - autoheal_containers_quarantined
# - autoheal_health_checks_total
# - autoheal_health_checks_failed
```

### Logs
```bash
# View all logs
docker logs docker-autoheal

# Follow logs
docker logs -f docker-autoheal

# Last 100 lines
docker logs --tail 100 docker-autoheal

# Since timestamp
docker logs --since 2024-10-30T10:00:00 docker-autoheal
```

## 🎓 Usage Examples

### Example 1: Monitor Nginx Container
```yaml
# docker-compose.yml
services:
  nginx:
    image: nginx:alpine
    labels:
      - "autoheal=true"
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Example 2: Selective Monitoring
```bash
# Via UI:
1. Open http://localhost:3131
2. Go to Containers tab
3. Check the containers you want to monitor
4. Click "Enable Auto-Heal"
```

### Example 3: Export Configuration Before Changes
```bash
# Export current config
curl -O http://localhost:3131/api/config/export

# Make changes in UI
# If something goes wrong, import the backup
```

## 🛠️ Troubleshooting

### Issue: Service won't start
```bash
# Check Docker is running
docker info

# Check socket permissions (Linux)
ls -l /var/run/docker.sock

# View startup logs
docker logs docker-autoheal
```

### Issue: Container not monitored
1. ✅ Has `autoheal=true` label?
2. ✅ Not in excluded list?
3. ✅ Passes whitelist/blacklist filters?
4. ✅ Check Events tab for decision

### Issue: Too many restarts
```bash
# Increase cooldown
# Configuration → Restart Policy → Cooldown: 120 seconds

# Or increase max restarts threshold
# Configuration → Restart Policy → Max Restarts: 5
```

## 📈 Production Recommendations

### Security
1. Add reverse proxy with authentication (nginx, traefik)
2. Use firewall rules to restrict access
3. Enable TLS/SSL for web UI
4. Regular configuration backups
5. Monitor the monitoring service itself

### Performance
1. Adjust monitoring interval based on load
2. Use custom health checks sparingly
3. Set appropriate cooldowns
4. Monitor Prometheus metrics

### Reliability
1. Set `restart: unless-stopped` for auto-heal container
2. Label auto-heal with `autoheal=false`
3. Regular config exports
4. Test restart policies in staging first
5. Set up alerting for quarantine events

## 📚 Documentation Files

| File | Purpose |
|------|---------|
| **README.md** | Complete documentation with all features |
| **QUICKSTART.md** | Get started in 5 minutes |
| **IMPLEMENTATION.md** | Technical details and decisions |
| **config-example.json** | Sample configuration |
| **demo.py** | Interactive testing and demonstration |

## ✅ BRD Compliance Checklist

All requirements from the Business Requirements Document have been implemented:

- ✅ Label-driven monitoring (`autoheal=true`)
- ✅ Restart on failure (non-zero exit codes)
- ✅ Restart on health check failures
- ✅ Cooldown periods
- ✅ Restart thresholds and quarantine
- ✅ Exponential backoff
- ✅ Whitelist/blacklist filtering
- ✅ Web UI with container listing
- ✅ Interactive container selection
- ✅ Configuration management UI
- ✅ In-memory state storage
- ✅ JSON export/import
- ✅ Event history display
- ✅ Python implementation
- ✅ Custom health checks (HTTP, TCP, Exec, Docker)
- ✅ Prometheus metrics
- ✅ Webhook alerting support
- ✅ Thread-safe operations
- ✅ Docker Compose deployment

## 🎉 Project Status

**Status**: ✅ **COMPLETE & PRODUCTION READY**

**What works:**
- ✅ All core functionality
- ✅ All BRD requirements met
- ✅ Web UI fully functional
- ✅ API fully operational
- ✅ Docker deployment ready
- ✅ Comprehensive documentation
- ✅ Test environment included
- ✅ Demo scripts provided

**Ready for:**
- ✅ Local development and testing
- ✅ Docker deployment
- ✅ Production use (with proper security setup)
- ✅ Integration with existing Docker infrastructure

## 🚀 Next Steps

1. **Start the service:**
   ```bash
   docker-compose up -d
   ```

2. **Open the UI:**
   ```
  http://localhost:3131
   ```

3. **Add containers to monitor:**
   - Label existing containers with `autoheal=true`, OR
   - Use UI to select containers

4. **Configure to your needs:**
   - Adjust monitoring interval
   - Set restart policies
   - Add custom health checks

5. **Monitor operations:**
   - Check Events tab
   - Review Prometheus metrics
   - Watch logs

## 💡 Tips & Best Practices

1. **Start with conservative settings**: Use longer cooldowns and lower restart limits initially
2. **Test in staging first**: Validate restart behavior before production
3. **Export configs regularly**: Backup your configuration
4. **Monitor the monitor**: Set up alerts if auto-heal service fails
5. **Use health checks**: Add proper health checks to your containers
6. **Review events**: Check the event log to understand auto-heal decisions
7. **Gradual rollout**: Enable auto-heal for a few containers first

## 📞 Getting Help

- **Documentation**: Start with QUICKSTART.md
- **API Docs**: http://localhost:3131/docs
- **Demo**: Run `python demo.py --interactive`
- **Logs**: `docker logs -f docker-autoheal`
- **Issues**: Check IMPLEMENTATION.md for technical details

---

**Version**: 1.1.0
**Date**: October 30, 2025
**Language**: Python 3.11+
**Framework**: FastAPI + Bootstrap 5
**Status**: Production Ready ✅

**Built with ❤️ following the complete BRD specification**

