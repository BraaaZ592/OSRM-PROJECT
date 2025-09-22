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

Benefícios para a empresa
- Controle total sobre o motor de rotas (sem depender de terceiros).
- Custo zero por requisição.
- Integração em sistemas internos.
- Escalável.

Próximos passos
- Automatizar atualização mensal do mapa.
- Criar interface web simples.
- Adicionar perfis diferentes (carro, bike, pedestre) que já existem no OSRM, apenas precisa alterar o perfil por exemplode car.lua para bike.lua.