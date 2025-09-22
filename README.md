                                                   -- es-ES -- 

¿Qué es OSRM?
OSRM es un motor de enrutamiento de código abierto que puede calcular rutas, distancias y tiempos de viaje. Utiliza datos de OpenStreetMap y puede ejecutarse localmente en contenedores Docker.

Como está estructurado?
-Docker: ejecuta el servidor de OSRM.
-Mapa de SP: se descarga del sitio web de Geofabrik.
-Scripts de Python: procesan archivos JSON de rutas (con coordenadas GPS sin procesar), limpian los datos y solicitan a OSRM que alinee los puntos a la red vial (map matching).
-Salida: genera un GeoJSON con la ruta ajustada.

Como rodar
1. Preparar el ambiente
- Tener Docker y Python instalados.
- Descargar el archivo sao-paulo.osm.pbf en la carpeta data/. 
(No solo existe el mapa de SP para descargar; descargué el sureste de Brasil y corté el mapa de SP, pero puedes usar el mapa completo de Brasil sin problemas).
2. Subir el OSRM
docker-compose up -d
Esto inicia el servidor en el puerto 5000 o 5001 (que es el que estoy usando en mi computadora).
3. Ejecutar el script
Dentro de VS Code, haz clic en "Run" y el script abrirá el explorador y te pedirá que selecciones el archivo JSON con la ruta. Después de eso, generará un archivo llamado ruta_unificada.geojson en Documents/geojson. (Puedes ajustar la ruta final).

O que os scripts fazem
- processador_rotas_unificado_sem_valhalla.py: procesa rutas sin procesar, filtra duplicados, detecta espacios vacíos (gaps) y llama a OSRM (/match y /route). Exporta en GeoJSON.
- processador_rotas_unificado.py: versión anterior con soporte para Valhalla que aún está en pruebas; estoy probando algunas posibilidades y variaciones.
- valhalla.py: script auxiliar para la comparación entre OSRM y Valhalla.
- docker-compose.yml: define el contenedor de OSRM.
- start-docker-uvicorn.bat: script de inicio en Windows para agilizar el proceso; la inicialización de Docker y Uvicorn se puede hacer manualmente.

Fluxo resumido
1. Recibe archivos JSON con coordenadas sin procesar.
2. Python procesa y los envía a OSRM.
3. OSRM devuelve las rutas.
4. Python organiza y guarda en GeoJSON.

Próximos passos
- Automatizar la actualización mensual del mapa.
- Crear una interfaz web sencilla.
- Añadir diferentes perfiles (coche, bicicleta, peatón) que ya existen en OSRM; solo se necesita cambiar el perfil, por ejemplo, de car.lua a bike.lua.


                                                   -- PT-BR -- 


O que é o OSRM?
O OSRM é um motor de roteamento open-source, que consegue calcular rotas, distâncias e tempos de viagem.
Ele utiliza dados do OpenStreetMap e pode rodar localmente em containers Docker.

Como está estruturado?
- Docker: roda o servidor do OSRM.
- Mapa de SP: baixado do site Geofabrik.
- Scripts Python: processam arquivos JSON de rotas (com coordenadas brutas do GPS), limpam os dados e pedem ao OSRM para alinhar os pontos à malha viária (map matching).
- Saída: gera um GeoJSON com a rota ajustada.

Como rodar
1. Preparar o ambiente
- Ter Docker e Python instalados.
- Baixar o arquivo sao-paulo.osm.pbf para a pasta data/. 
(Não existe apenas o mapa de SP para download, eu baixei o sudeste do Brasil e cortei o mapa de SP, mas pode usar o mapa inteiro do Brasil sem problemas)
2. Subir o OSRM
docker-compose up -d
Isso inicia o servidor na porta 5000 ou 5001 (que é a que eu estou usando no meu computador).
3. Executar o script
Dentro do vs clique em run e o script vai abrir o explorer e pedir para selecionar o arquivo json com a rota, após isso ele vai gerar um arquivo chamado rota_unificada.geojson em Documents/geojson.  (pode ajustar o caminho final)


O que os scripts fazem
- processador_rotas_unificado_sem_valhalla.py: processa rotas brutas, filtra duplicados, detecta gaps e chama o OSRM (/match e /route). Exporta em GeoJSON.
- processador_rotas_unificado.py: versão anterior com suporte ao Valhalla que ainda está em testes, estou testando algumas possibilidades e variações.
- valhalla.py: script auxiliar para comparação entre OSRM e Valhalla.
- docker-compose.yml: define o container OSRM.
- start-docker-uvicorn.bat: script de inicialização no Windows para agilizar o processo, pode ser feito manualmente a inicialização do docker e uvicorn.

Fluxo resumido
1. Recebe arquivos JSON com coordenadas brutas.
2. Python processa e manda para o OSRM.
3. OSRM retorna as rotas.
4. Python organiza e salva em GeoJSON.

Próximos passos
- Automatizar atualização mensal do mapa.
- Criar interface web simples.
- Adicionar perfis diferentes (carro, bike, pedestre) que já existem no OSRM, apenas precisa alterar o perfil por exemplode car.lua para bike.lua.
