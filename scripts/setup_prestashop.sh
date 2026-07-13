#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Arrancando contenedores ==="
docker compose up -d
echo ""

# Esperar a que PrestaShop responda (puede tardar 2-3 min la instalación)
echo "=== Esperando a que PrestaShop esté disponible (http://localhost:8080) ==="
for i in $(seq 1 60); do
  status=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ 2>/dev/null || echo "000")
  if [ "$status" = "200" ] || [ "$status" = "302" ]; then
    echo "  PrestaShop responde (HTTP $status) después de ${i}s"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "  ERROR: PrestaShop no respondió después de 60 intentos"
    exit 1
  fi
  sleep 5
done

# La instalación automática puede seguir corriendo aunque ya responda HTTP
echo "  Esperando 30s adicionales para que termine la instalación automática..."
sleep 30

# Habilitar webservice y crear API key
echo "=== Configurando webservice y API key ==="
API_KEY=$(openssl rand -hex 16)
echo "  API Key generada: $API_KEY"

docker compose exec -T db mariadb -u root -proot123 prestashop <<SQL
UPDATE ps_configuration SET value = '1' WHERE name = 'PS_WEBSERVICE';
INSERT IGNORE INTO ps_webservice_account (active, \`key\`, description, class_name, is_module)
VALUES (1, '${API_KEY}', 'Middleware Icecat', 'WebserviceRequest', 0);
INSERT IGNORE INTO ps_webservice_account_shop (id_webservice_account, id_shop)
SELECT LAST_INSERT_ID(), id_shop FROM ps_shop;
INSERT INTO ps_webservice_permission (resource, method, id_webservice_account)
SELECT r.resource, m.method, (SELECT id_webservice_account FROM ps_webservice_account WHERE \`key\` = '${API_KEY}')
FROM
  (SELECT 'products' AS resource UNION SELECT 'product_features' UNION SELECT 'product_feature_values' UNION SELECT 'features' UNION SELECT 'categories' UNION SELECT 'manufacturers' UNION SELECT 'images' UNION SELECT 'stock_availables' UNION SELECT 'combinations' UNION SELECT 'product_option_values' UNION SELECT 'product_options' UNION SELECT 'groups' UNION SELECT 'addresses' UNION SELECT 'currencies' UNION SELECT 'languages' UNION SELECT 'countries' UNION SELECT 'states' UNION SELECT 'carriers') r,
  (SELECT 'GET' AS method UNION SELECT 'HEAD' UNION SELECT 'POST' UNION SELECT 'PUT' UNION SELECT 'PATCH' UNION SELECT 'DELETE') m;
SQL

echo ""
echo "=== Listo ==="
echo ""
echo "Agrega esto a tu .env:"
echo ""
echo "  PRESTASHOP_API_URL=http://localhost:8080/api"
echo "  PRESTASHOP_API_KEY=${API_KEY}"
echo ""
echo "Backoffice:  http://localhost:8080/admin"
echo "Usuario:     admin@prestashop.com"
echo "Contraseña:  admin123"
