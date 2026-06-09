# CoRE Stack — FPL Linux Setup

**Time:** ~20 minutes. Get `core-stack-key.json` from #fpl-esg before starting.

---

## 1. Clone

```bash
git clone https://github.com/fplaunchpad/core-stack-backend.git
cd core-stack-backend
```

## 2. Start GeoServer

Install Docker if needed (`sudo apt-get install docker.io`), then:

```bash
sudo docker run -d --name geoserver -p 8080:8080 \
  -e GEOSERVER_ADMIN_PASSWORD=geoserver \
  kartoza/geoserver:2.25.2
```

Start this before running the installer — the installer's GeoServer step will wait for it.

## 3. Run the installer

```bash
bash installation/install.sh \
  --gee-json /path/to/core-stack-key.json \
  --geoserver-config http://localhost:8080/geoserver,admin,geoserver
```

This handles: Miniconda, PostgreSQL, RabbitMQ, Python env, migrations, seed data, superuser (`admin`/`admin`), GEE key loading, and all GeoServer workspaces.

## 4. Add FPL-specific .env vars

The installer generates `nrm_app/.env`. Append these lines:

```env
GEE_STORAGE_PROJECT=arcane-mason-493503-a6
GEE_STORAGE_PROJECT_HELPER=arcane-mason-493503-a6
GCS_BUCKET_NAME=fpl-core-stack-dev
```

## 5. Verify

```bash
conda activate corestackenv
python computing/misc/internal_api_initialisation_test.py --require-gee
```

Expected: `Internal API initialisation test passed.`

---

## Daily use

```bash
conda activate corestackenv
sudo docker start geoserver     # if not already running
python manage.py runserver 0.0.0.0:8000 --noreload
```
