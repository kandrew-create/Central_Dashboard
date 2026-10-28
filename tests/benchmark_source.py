"""Explicit disposable-source benchmark. Never use a customer database."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import tempfile
import time
from uuid import uuid4

import psycopg

from collector.desktop import default_config
from collector.source import SourceReader
from tests.pg_support import PostgresCase,ROOT


def main():
    PostgresCase.setUpClass()
    role='benchmark_'+uuid4().hex
    try:
        PostgresCase._run(f'''CREATE ROLE "{role}" LOGIN; GRANT USAGE ON SCHEMA public TO "{role}";
            GRANT SELECT ON public.alarmhistory,public.eventhistory TO "{role}";
            INSERT INTO public.alarmhistory(al_tag,al_message,al_start_time,al_start_time_ms,last_update,last_update_ms,al_active)
            SELECT 'TAG-'||(g%100),repeat('sample ',10),'2026-10-28 00:00'::timestamp+make_interval(secs=>g/1000),g%1000,
                CASE WHEN g%10=0 THEN NULL ELSE '2026-10-28 00:00'::timestamp+make_interval(secs=>g/1000) END,g%1000,true
            FROM generate_series(1,150000) g;
            INSERT INTO public.eventhistory(ev_source,ev_message,ev_time,ev_time_ms,last_update,last_update_ms)
            SELECT 'SOURCE-'||(g%100),'synthetic event','2026-10-28 00:00'::timestamp+make_interval(secs=>g/1000),g%1000,
                CASE WHEN g%10=0 THEN NULL ELSE '2026-10-28 00:00'::timestamp+make_interval(secs=>g/1000) END,g%1000
            FROM generate_series(1,150000) g;
            ANALYZE public.alarmhistory; ANALYZE public.eventhistory;''')
        with tempfile.TemporaryDirectory() as temporary:
            config=replace(default_config(Path(temporary)/'config.toml'),host='127.0.0.1',port=int(os.environ['PGPORT']),database=PostgresCase.database,
                           user=role,scan_mode='marker',marker_verified=True,page_rows=50)
            reader=SourceReader(config,'')
            start=time.perf_counter()
            bounds=reader.bounds()
            result={'measured_at':datetime.now(timezone.utc).isoformat(),'environment':{'python':platform.python_version(),'platform':platform.platform(),'logical_cpus':os.cpu_count()},
                    'rows':{'alarmhistory':150000,'eventhistory':150000},'indexes':'primary keys only; no last_update index',
                    'bounds_ms':round((time.perf_counter()-start)*1000,3),'pages':[],'plans':{}}
            for table in ('alarmhistory','eventhistory'):
                for phase,cursor in (('ids',75000),('marker',None)):
                    started=time.perf_counter()
                    rows=reader.scan_page(table,phase,bounds[table],cursor)
                    result['pages'].append({'table':table,'phase':phase,'returned':len(rows),'latency_ms':round((time.perf_counter()-started)*1000,3)})
                query=f'''EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT id FROM public.{table}
                    WHERE last_update IS NOT NULL ORDER BY last_update,last_update_ms,id LIMIT 50;'''
                plan=json.loads(PostgresCase._run(query).stdout.strip())
                result['plans'][table]=plan
            PostgresCase._run("UPDATE public.alarmhistory SET last_update='2026-10-28 01:00',last_update_ms=123 WHERE id>140000;")
            started=time.perf_counter()
            peak=reader.bounds()
            page=reader.scan_page('alarmhistory','marker',peak['alarmhistory'],lower='2026-10-28T01:00:00')
            result['burst']={'changed_rows':10000,'returned':len(page),'bounds_and_page_ms':round((time.perf_counter()-started)*1000,3)}
            with reader.session() as db:
                db.execute("SET statement_timeout=1")
                try:
                    db.execute('SELECT id FROM public.alarmhistory ORDER BY last_update,last_update_ms,id LIMIT 50')
                    result['one_ms_timeout']='query completed within configured limit'
                except psycopg.errors.QueryCanceled:
                    result['one_ms_timeout']='query cancelled as required'
            target=ROOT/'.tools/source-benchmark-results.json'
            target.write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in result.items() if k!='plans'},indent=2))
    finally:
        PostgresCase._run(f'DROP OWNED BY "{role}";')
        PostgresCase._run(f'DROP ROLE "{role}";',database=PostgresCase.base_database)
        PostgresCase.doClassCleanups()


if __name__=='__main__':
    main()
