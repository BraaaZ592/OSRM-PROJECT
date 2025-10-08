                                                   -- es-ES -- 

Visión general del OSRM y del sistema actual
OSRM es un motor de enrutamiento open-source que permite calcular rutas, distancias y tiempos de viaje.
Utiliza datos de OpenStreetMap y puede ejecutarse localmente en contenedores Docker.

Cómo está estructurado?
- Docker: ejecuta el servidor de OSRM.
- Mapa de SP: descargado del sitio web de Geofabrik.
- Scripts de Python: procesan archivos JSON de rutas (con coordenadas GPS sin procesar), limpian los datos y solicitan a OSRM que alinee los puntos a la red vial (map matching).
- Salida: genera un GeoJSON con la ruta ajustada.

Cómo ejecutar
1. Preparar el entorno
- Tener instalados Docker y Python.
- Descargar el archivo sao-paulo.osm.pbf en la carpeta data/.
(No existe un archivo exclusivamente de São Paulo; se puede descargar el del sudeste de Brasil y recortarlo, o utilizar el mapa completo de Brasil sin problema).

2. Levantar el OSRM
docker-compose up -d
Esto inicia el servidor en el puerto 5000 o 5001 (que es el que utilizo en mi equipo).

3. Ejecutar el procesador
Dentro de Visual Studio Code, haz clic en Run y selecciona el archivo JSON con la ruta.
El script procesará el archivo y generará rota_unificada.geojson en Documents/geojson/ (se puede ajustar la ruta de salida si se desea).


Qué hacen los scripts
- processador_rotas_unificado_sem_valhalla.py: procesa rutas brutas, elimina duplicados, detecta gaps y llama al OSRM (/match y /route). Exporta el resultado en GeoJSON.
- processador_rotas_unificado.py: versión anterior con soporte para Valhalla, actualmente en pruebas.
- valhalla.py: script auxiliar para comparar resultados entre OSRM y Valhalla.
- docker-compose.yml: define el contenedor de OSRM.
- start-docker-uvicorn.bat: script de inicialización para Windows que acelera el proceso, también se puede hacer manualmente la inicialización de docker y uvicorn.

Flujo resumido:
Entrada → Normalización → Matching (OSRM → Valhalla → Fallback) → Postprocesamiento → Métricas → Exportación (GeoJSON/JSON)

Próximos pasos
- Automatizar la actualización mensual del mapa.
- Crear una interfaz web sencilla.
- Añadir perfiles de enrutamiento diferentes (auto, bicicleta, peatón), que ya existen en OSRM; basta con cambiar el perfil, por ejemplo de car.lua a bike.lua.


=====================================================================================================================================================================================================
====================================================================================================================================================================================


El sistema actual ya ejecuta el pipeline de map matching localmente (OSRM + Valhalla) con buenos resultados, aunque todavía presenta variaciones de calidad y fallos en zonas urbanas complejas.
Este documento consolida mejoras destinadas a aumentar la precisión, la previsibilidad y la auditabilidad del procesamiento, manteniendo la operación completamente offline.

Flujo resumido:
Entrada → Normalización → Matching (OSRM → Valhalla → Fallback) → Postprocesamiento geométrico → Cálculo de métricas → Exportación GeoJSON/JSON.
Cada mejora se aplica a una de estas etapas.


MEJORAS:
Objetivo
Hacer que el procesador de rutas local (OSRM + Valhalla) sea más preciso, robusto y predecible, alcanzando una calidad equivalente a las API comerciales (por ejemplo, Google Roads/Directions), manteniendo el control local sobre los datos.

Prioridades rápidas
Reintentos y caché con TTL: agregar reintento exponencial con jitter y caché en disco con TTL para las llamadas HTTP. Esto reduce errores intermitentes, disminuye la latencia en datos repetidos y alivia la carga sobre la infraestructura, logrando una ejecución más estable y predecible.

Métricas de calidad: generar matched_ratio, desviación media/máxima raw→matched (m), número/tiempo de gaps y total_route_length (m), y guardarlas en el GeoJSON.
- Registrar y almacenar métricas como matched_ratio, desviaciones, número/tiempo de gaps y longitud total hace que el proceso sea verificable, fácil de monitorear y más rápido de diagnosticar problemas.

Registro estructurado (logging): registrar logs en formato JSON con host utilizado, fallos, reintentos y motivo del fallback; incluir log_version, osrm_host, valhalla_host y cache_hit en cada registro.
- Esto permite rastrear qué instancia y qué respuesta se usó en cada ruta (útil para entornos distribuidos o clústeres).

Map Matching y Fallback
Preservar índices del OSRM: usar matchings[].indices para mapear puntos originales con la geometría cuando esté disponible.
- Preservar estos índices mejora la precisión, las métricas y las decisiones de fallback, siendo una de las mejoras de mayor impacto para la calidad y la auditabilidad.

Valhalla con timestamps: enviar timestamps o velocidades estimadas entre puntos para mejorar el map matching.
- Incluir información temporal hace que el emparejamiento sea más realista y confiable.

Fallback robusto: cuando falle /match, subdividir el segmento en checkpoints (por ejemplo, cada 100–200 m) y usar /route multipunto por pares consecutivos antes de volver a los datos originales.
Resultado práctico: rutas más continuas y realistas cuando el map matching falla, con rastreabilidad total y posibilidad de revisión manual o reprocesamiento controlado.

Detección y tratamiento de gaps
Detección adaptativa: clasificar los gaps según delta-time, delta-distancia, variación de heading y, si está disponible, HDOP; etiquetar los gaps como pause/teleport/loss.

Costura segura: para gaps largos, evitar conectar los puntos directamente; usar enrutamiento intermedio y registrar el tipo/razón del gap en las propiedades del GeoJSON.

Postprocesamiento geométrico
Filtro preservador de aristas: aplicar un filtro preservador de aristas, combinando Chaikin con un filtro bilateral geográfico o aplicando Ramer–Douglas–Peucker en metros después de la densificación, esto va a producir rutas visualmente más limpias y geométricamente más confiables que preservan nodos importantes, reducen ruido y mantienen la topología, mejorando tanto la UX como la calidad de las métricas.

Densificación en metros: usar step en metros y validar desviación máxima en metros para evitar alterar la topología real de la vía.
Básicamente tendrá rutas más limpias y confiables, lo que significa que el trazo final será estéticamente mejor para visualización, mantendrá las curvas y cruces reales del mapa, reducirá el ruido del GPS y preservará la topología de la vía, lo que aumenta la confianza en las métricas (distancia, desviaciones, matching) y facilita el análisis, la depuración y el uso por otras aplicaciones.

Enriquecimiento de la salida
Propiedades por Feature: provider_used (osrm|valhalla|fallback), distance_m, duration_s (estimada), quality_score, gap_info.

Metadatos por punto: por punto incluir snapped (bool), matched_index, dist_to_raw_m.

Falla segura: exportar segmentos originales con propiedad indicando razón del fallback (timeout, no_match, etc.).

Validación y pruebas
Métricas esenciales: matched_ratio, mean_distance_raw_to_matched_m, max_distance_raw_to_matched_m, total_route_length_m, number_of_gaps, total_gap_time_s.
- Agregar script de sanity check posterior a la ejecución: alerta automática si matched_ratio < 0.8 o max_deviation > 30m (hace que el pipeline se autoaudite).

Fixtures mínimas: urbano denso, autopista de alta velocidad, teleport/jump, loop.

Umbrales sugeridos: matched_ratio > 0.9, max_deviation < 20 m (ajustables tras validación).

Cambios recomendados en infraestructura y código
Sustituir requests.get directos por función con retry y backoff.

Implementar caché basada en hash de payload (coords+timestamps+params) con TTL e invalidación.

Extraer matchings[].indices del OSRM y reconstruir correspondencia punto a punto cuando sea posible.

Implementar función de cálculo de desviación máxima entre puntos brutos y ruta ajustada para quality_score.
- quality_score = w1 * matched_ratio 
                - w2 * (mean_dev / 20)
                - w3 * (gap_time_ratio)

Registrar y guardar en el GeoJSON las nuevas propiedades y métricas.




                                                   -- PT-BR -- 




Visão geral do OSRM e do sistema atual
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
3. Executar o processador
Dentro do Visual Studio Code, clique em Run e selecione o arquivo JSON com a rota.
O script processará o arquivo e gerará rota_unificada.geojson em Documents/geojson/ (pode ajustar o caminho de saída conforme necessário).


O que os scripts fazem
- processador_rotas_unificado_sem_valhalla.py: processa rotas brutas, filtra duplicados, detecta gaps e chama o OSRM (/match e /route). Exporta em GeoJSON.
- processador_rotas_unificado.py: versão anterior com suporte ao Valhalla que ainda está em testes, estou testando algumas possibilidades e variações.
- valhalla.py: script auxiliar para comparação entre OSRM e Valhalla.
- docker-compose.yml: define o container OSRM.
- start-docker-uvicorn.bat: script de inicialização no Windows para agilizar o processo, pode ser feito manualmente a inicialização do docker e uvicorn.

Fluxo resumido:
Entrada → Normalização → Matching (OSRM → Valhalla → Fallback) → Pós-processamento → Métricas → Exportação (GeoJSON/JSON)

Próximos passos
- Automatizar atualização mensal do mapa.
- Criar interface web simples.
- Adicionar perfis diferentes (carro, bike, pedestre) que já existem no OSRM, apenas precisa alterar o perfil por exemplode car.lua para bike.lua.


=====================================================================================================================================================================================================
====================================================================================================================================================================================


O sistema atual já executa o pipeline de map matching localmente (OSRM + Valhalla) com bons resultados, porém ainda apresenta variações de qualidade e falhas em casos urbanos complexos. Este documento consolida melhorias destinadas a aumentar a precisão, previsibilidade e auditabilidade do processamento, mantendo operação offline.

 
Fluxo resumido:
Entrada → Normalização → Matching (OSRM → Valhalla → Fallback) → Pós-processamento geométrico → Cálculo de métricas → Export GeoJSON/JSON.
Cada melhoria se aplica a uma dessas camadas.


MELHORIAS:
Objetivo
Tornar o processador de rotas local (OSRM + Valhalla) mais preciso, robusto e previsível, equivalente em qualidade às APIs comerciais (ex.: Google Roads/Directions), mantendo operação offline e controle sobre dados.

Prioridades rápidas
Retries e cache TTL: adicionar retry exponencial com jitter e cache em disco com TTL para chamadas HTTP. Isso causa menos erros intermitentes, menor latência para dados repetidos e menos carga na infraestrutura, resultando em execução mais estável e previsível.

Métricas de qualidade: gerar matched_ratio, mean/max desvio raw→matched (m), número/tempo de gaps, total_route_length (m) e salvar no GeoJSON. 
- Gerar e salvar métricas como matched_ratio, desvio médio/máximo, número/tempo de gaps e comprimento total torna o processo verificável, mais fácil de monitorar e mais rápido de diagnosticar problemas.

Logging estruturado: logs em JSON com host usado, falhas, retries e motivo de fallback, gravar log_version, osrm_host, valhalla_host e cache_hit em cada registro.
- Isso viabiliza traçar qual instância e qual resposta foi usada em cada rota (útil para clusters).

Map matching e fallback
Preservar índices do OSRM: usar matchings[].indices para mapear pontos originais à geometria quando disponível. 
- Preservar matchings[].indices oferece precisão, melhores métricas e decisões de fallback mais inteligentes sem custo significativo, e é uma das mudanças de maior impacto para melhorar qualidade e auditabilidade do processamento.

Valhalla com timestamps: enviar timestamps ou velocidades estimadas entre pontos para melhorar o map-matching.  
- Enviar timestamps ou velocidades fará o matcher usar informação temporal além da geometria, resultando em correspondências mais realistas e confiáveis.

Fallback robusto: ao falhar /match, subdividir o segmento em checkpoints (ex.: a cada 100–200 m) e tentar /route multi por pares consecutivos antes de retornar ao raw.
Resultado prático: rotas mais contínuas e realistas quando o map-matching falha, com rastreabilidade total e possibilidade de revisão manual ou reprocessamento controlado.

Detecção e tratamento de gaps
Detecção adaptativa: classificar gaps por delta-time, delta-distância, variação de heading e, se disponível, HDOP; rotular gaps como pause/teleport/loss.

Costura segura: para gaps longos evitar ligar pontos diretamente; usar roteamento intercalar e registrar tipo/razão do gap nas propriedades do GeoJSON.

Pós-processamento geométrico
Filtro preservador de arestas: Aplicar filtro preservador de arestas, combinando Chaikin com filtro bilateral geográfico ou aplicando Ramer–Douglas–Peucker em metros após densificação, isso vai tornar as rotas visualmente mais limpas e matematicamente confiáveis que preservam nós importantes, reduzem ruído e mantêm topologia, melhorando tanto a UX quanto a qualidade das métricas.

Densificação em metros: usar step em metros e validar desvio máximo em metros para evitar alterar topologia real da via.
Basicamente terá rotas mais limpas e confiáveis e isso significa que o traço final fica esteticamente melhor para visualização, mantém as curvas e cruzamentos reais do mapa, reduz o ruído do GPS e preserva a topologia da via, o que aumenta a confiança nas métricas (distância, desvios, matching) e facilita análise, depuração e uso por outras aplicações.

Enriquecimento da saída
Propriedades por Feature: provider_used (osrm|valhalla|fallback), distance_m, duration_s (estimada), quality_score, gap_info.

Metadados por ponto: por ponto incluir snapped (bool), matched_index, dist_to_raw_m.

Falha segura: exportar segmentos originais com propriedade indicando razão do fallback (timeout, no_match, etc.).

Validação e testes
Métricas essenciais: matched_ratio, mean_distance_raw_to_matched_m, max_distance_raw_to_matched_m, total_route_length_m, number_of_gaps, total_gap_time_s.
- Adicionar script de sanity check pós-execução: alerta automático se matched_ratio < 0.8 ou max_deviation > 30m   (faz o pipeline se auto-auditar).

Fixtures mínimas: urbano denso, rodovia alta velocidade, teleport/jump, loop.

Thresholds sugeridos: matched_ratio > 0.9, max_deviation < 20 m (ajustáveis após validação).

Mudanças de infra e código recomendadas
Substituir requests.get diretos por função com retry e backoff.

Implementar cache baseado em hash de payload (coords+timestamps+params) com TTL e invalidação.

Extrair matchings[].indices do OSRM e reconstruir correspondência ponto-a-ponto quando possível.

Implementar função de cálculo de desvio máximo entre pontos brutos e rota matchada para quality_score.
- quality_score = w1 * matched_ratio 
                - w2 * (mean_dev / 20)
                - w3 * (gap_time_ratio)

Logar e salvar no GeoJSON as novas propriedades e métricas.



