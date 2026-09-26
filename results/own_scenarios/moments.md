# Моменты собственных сценариев (переснято финальным контроллером)

Все прогоны выполнены контроллером `team_dreamteam_4_0/controller.py`, sha256 `560f0b56f50034fd` (16 hex-символов, как в отчетах). Данные ниже извлечены из фактических логов JSONL (строки `type=tick`) и отчетов, значения не корректировались.

Проверка отчетов: во всех семи отчетах `counted=true`, `score.fatal=false`, `score.blocks.collisions=0.0`, `sandbox_violations=[]`, `controller.path="team_dreamteam_4_0/controller.py"`.

## Таблица моментов

| Сценарий | Seed | Total | Момент | t, с | Статус | Note | Файл лога |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s1_pallet_2m | 7 | 99.52 | offset | 115.3 | moving | offset dy=-0.2 | results/own_scenarios/logs/s1_pallet_2m.jsonl |
| s2_container_block | 7 | 100.0 | replan | 147.0 | moving | replan | results/own_scenarios/logs/s2_container_block.jsonl |
| s3_wall_removed | 7 | 100.0 | map_missing | 9.8 | moving | map_missing | results/own_scenarios/logs/s3_wall_removed.jsonl |
| s4_shadow_start_charger | 7 | 100.0 | arrival_charger | 42.0 | arrived | dock | results/own_scenarios/logs/s4_shadow_start_charger.jsonl |
| s4b_shadow_lane_lost | 7 | 100.0 | lane_lost_status | - | - | не найдено: на seed 7 потеря ориентации не возникала | results/own_scenarios/logs/s4b_shadow_lane_lost.jsonl |
| s5_fog_inattentive | 7 | 99.43 | stop_person | 87.4 | waiting | stop_person d=0.8 slow_person d=3.0 fog_clear zone v=0.95 | results/own_scenarios/logs/s5_fog_inattentive.jsonl |
| 04_busy_yard | 7 | 98.87 | stop_person | 263.5 | waiting | stop_person d=0.7 map_extra zone v=0.95 | results/table_runs/logs/team_dreamteam_4_0__04_busy_yard__s7.jsonl |
| s4b_shadow_lane_lost | 1 | 100.0 | pre_loss | 25.9 | moving | map_extra | results/own_scenarios/logs/s4b_shadow_lane_lost_seed1.jsonl |
| s4b_shadow_lane_lost | 1 | 100.0 | lane_lost_nt | 26.0 | moving | lost s_lat=0.0 map_extra | results/own_scenarios/logs/s4b_shadow_lane_lost_seed1.jsonl |
| s4b_shadow_lane_lost | 1 | 100.0 | lane_lost_status | 27.2 | lost | lost s_lat=0.0 map_extra | results/own_scenarios/logs/s4b_shadow_lane_lost_seed1.jsonl |
| s4b_shadow_lane_lost | 1 | 100.0 | motion_resume | 28.0 | waiting | map_extra | results/own_scenarios/logs/s4b_shadow_lane_lost_seed1.jsonl |

Канонический seed - 7. Для момента потери ориентации основной прогон - s4b на seed 1: только на нем локализация срывается и появляется `st=lost`; на seed 7 потеря не возникает.

## s4b, seed 1: потеря ориентации и восстановление

На seed 1 покрытая сервисная полоса дает вдоль-полосную необсервируемость, и локализация срывается. Такт непосредственно перед потерей - t=25.9, статус moving, note `map_extra`, скорость 1.39 м/с. Первое упоминание потери в note - t=26.0, статус еще moving, note `lost s_lat=0.0 map_extra`, скорость 1.39 м/с: контроллер обнаруживает потерю до того, как снимает движение. Полный статус `st=lost` наступает на t=27.2 (note `lost s_lat=0.0 map_extra`, v=0.0), то есть платформа уже остановлена. Участок `st=lost` длится с t=27.2 по t=27.9 (8 тактов). Восстановление начинается на t=28.0: статус waiting, v=0.0, note `map_extra`, затем движение плавно возобновляется с t=28.1 (v=0.05) и t=28.2 (moving, v=0.1). Итог прогона - миссия yard_s -> charger доставлена, total 100.0 при нулевых столкновениях.

Отдельно зафиксирован факт по seed 7: в логе `s4b_shadow_lane_lost.jsonl` нет ни одного такта со `st=lost` и ни одного note с подстрокой `lost` (контроллер прошел коридор без срыва локализации), поэтому момент `lane_lost_status` для seed 7 помечен `found=false`. Это фактическое поведение, а не пропуск в извлечении.

## s5, seed 7: туман и невнимательный пешеход

Сценарий содержит событие `fog_bank` с интервалом t1=40.0 - t2=130.0 и невнимательного пешехода. На такте t=87.4 в условиях активного тумана платформа останавливается перед пешеходом: расстояние hum=3.352 м (d=0.8 м до тормозного коридора), скорость v=0.0 м/с, статус waiting, note `stop_person d=0.8 slow_person d=3.0 fog_clear zone v=0.95`. Контроллер выполняет защитный останов без столкновения (collisions=0.0, fatal=false). Итог прогона - обе миссии доставлены, total 99.43, потеря баллов только по эффективности (14.43 из 15.0).

## 04_busy_yard, seed 7: пешеход во дворе

На такте t=263.5 (миссия m2) дорогу пересекает пешеход: расстояние hum=0.311 м, статус waiting, скорость v=0.0 м/с, note `stop_person d=0.7 map_extra zone v=0.95`. Контроллер выполняет защитный останов без столкновения (collisions=0.0) и без фатального исхода. После освобождения полосы движение возобновляется, обе миссии сданы, итоговый балл 98.87.

## Артефакты

- `results/own_scenarios/moments.json` - машиночитаемая версия таблицы (UTF-8, ensure_ascii=false, отступ 2);
- `results/own_scenarios/*.json` - семь отчетов: шесть на seed 7 и s4b на seed 1;
- `results/own_scenarios/logs/*.jsonl` - семь логов с теми же именами.