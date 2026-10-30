"""Native local Central Server window. All database/process work runs off Tk."""
import argparse
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox

from server import __version__
from collector.errors import CollectorError
from server.management.service import ManagerService,text
from server.management.settings import ServerSettings,load_settings,save_settings

NEW='<Create new>'
MODES={'Local testing (one PC)':'local','Network server (multiple collector PCs)':'network'}


class ManagerWindow:
    def __init__(self,root,service=None):
        self.root=root
        self.service=service or ManagerService()
        self.busy=False
        self.closing=False
        self.pending=queue.Queue()
        self.controls=[]
        self.registry={key:[] for key in ('customers','sites','projects','machines')}
        self.source_rows={}
        self.choice_maps={}
        self.status_text=tk.StringVar(root,'Checking the local Central Server...')
        self.health_text=tk.StringVar(root,'Not checked')
        self.endpoint=tk.StringVar(root)
        self.metrics=tk.StringVar(root,'Start the server to view received records and processing status.')
        self.details=tk.StringVar(root,'Select a registered SCADA source to export its collector setup.')
        self.ai_model=tk.StringVar(root,'qwen3:4b')
        self.ai_status=tk.StringVar(root,'Refresh interpretations to read the saved local AI configuration and results.')
        self.ai_rows={}
        s=self.service.settings
        self.data_dir=tk.StringVar(root,str(s.data_dir))
        self.postgres_bin=tk.StringVar(root,str(s.postgres_bin))
        self.database_port=tk.StringVar(root,str(s.database_port))
        self.https_port=tk.StringVar(root,str(s.https_port))
        self.mode=tk.StringVar(root,next(label for label,value in MODES.items() if value==s.mode))
        self.listen_address=tk.StringVar(root,s.listen_address)
        self.server_host=tk.StringVar(root,s.server_host)
        self.connection_summary=tk.StringVar(root)
        self.url_preview=tk.StringVar(root)
        self.names={name:tk.StringVar(root) for name in ('customer','site','project','machine','source')}
        self.choices={name:tk.StringVar(root,NEW) for name in ('customer','site','project','machine')}
        root.title('Central Server - Linker Enterprise')
        root.geometry('1220x830');root.minsize(1080,750)
        root.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('TFrame',background='#f3f6fa')
        style.configure('Card.TFrame',background='white')
        style.configure('TLabel',background='#f3f6fa',foreground='#17283e',font=('Segoe UI',10))
        style.configure('Card.TLabel',background='white',foreground='#17283e',font=('Segoe UI',10))
        style.configure('Title.TLabel',background='white',font=('Segoe UI',15,'bold'))
        style.configure('TButton',padding=(12,8),font=('Segoe UI',10))
        style.configure('TEntry',padding=6)
        style.configure('TCombobox',padding=6)
        style.configure('Treeview',rowheight=31,font=('Segoe UI',9))
        style.configure('Treeview.Heading',font=('Segoe UI',9,'bold'))
        style.configure('TNotebook.Tab',padding=(18,10),font=('Segoe UI',10,'bold'))
        style.configure('Horizontal.TProgressbar',background='#2265d7',troughcolor='#e8eef6',borderwidth=0)
        self._build()
        for variable in (self.mode,self.listen_address,self.server_host,self.https_port,self.database_port,self.data_dir,self.postgres_bin):
            variable.trace_add('write',self._settings_changed)
        self._preview_url()
        self.poll_id=root.after(80,self._poll)
        self.refresh()

    def button(self,parent,label,command):
        widget=ttk.Button(parent,text=label,command=command)
        self.controls.append((widget,'normal'))
        return widget

    def _build(self):
        header=tk.Frame(self.root,bg='#12243c',padx=28,pady=20)
        header.pack(fill='x')
        tk.Label(header,text='LINKER  /  SOFTWARE 2',fg='#a8c9ff',bg='#12243c',font=('Segoe UI',10,'bold')).pack(anchor='w')
        tk.Label(header,text='Central Server',fg='white',bg='#12243c',font=('Segoe UI',23,'bold')).pack(anchor='w',pady=5)
        tk.Label(header,text='Configure local or network operation, register sources and create collector setup files.',fg='#c7d4e5',bg='#12243c',font=('Segoe UI',10)).pack(anchor='w')
        outer=ttk.Frame(self.root,padding=22);outer.pack(fill='both',expand=True)
        self.notebook=ttk.Notebook(outer)
        tabs=[ttk.Frame(self.notebook,padding=16) for _ in range(5)]
        for tab,name in zip(tabs,('1  Server status','2  Register SCADA source','3  Sources & collector setup','4  Connection & mode','5  Local AI')):
            self.notebook.add(tab,text=name)
        self._status_tab(tabs[0]);self._registration_tab(tabs[1]);self._sources_tab(tabs[2])
        self._connection_tab(tabs[3])
        self._ai_tab(tabs[4])
        self.footer=ttk.Frame(self.root,padding=(24,12))
        self.footer.pack(side='bottom',fill='x',before=outer)
        self.progress=ttk.Progressbar(self.footer,mode='determinate',length=105)
        self.progress.pack(side='right',padx=(12,0))
        ttk.Label(self.footer,text='v'+__version__).pack(side='right',padx=12)
        status_label=ttk.Label(self.footer,textvariable=self.status_text,wraplength=860)
        status_label.pack(side='left',fill='x',expand=True)
        status_label.bind('<Configure>',lambda event:status_label.configure(wraplength=max(1,event.width)))
        self.notebook.pack(fill='both',expand=True)

    def _status_tab(self,parent):
        card=self._scroll_card(parent)
        ttk.Label(card,text='Server health',style='Title.TLabel').pack(anchor='w')
        ttk.Label(card,textvariable=self.health_text,style='Card.TLabel',font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(10,6))
        ttk.Label(card,textvariable=self.metrics,style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=4)
        ttk.Label(card,text='Saved record versions includes the first copy of each alarm or event. Unchanged records add nothing. '
                  'Batches awaiting machine mapping are saved and waiting for an approved machine assignment.',
                  style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=4)
        ttk.Label(card,textvariable=self.endpoint,style='Card.TLabel').pack(anchor='w',pady=4)
        bar=ttk.Frame(card,style='Card.TFrame');bar.pack(fill='x',pady=8)
        self.start_button=self.button(bar,'Initialize / start server',self.start_server)
        self.start_button.pack(side='left')
        self.button(bar,'Stop server',self.stop_server).pack(side='left',padx=8)
        self.button(bar,'Refresh',self.refresh).pack(side='left')
        ttk.Label(card,textvariable=self.connection_summary,style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=6)
        self.button(card,'Configure connection and mode',lambda:self.notebook.select(3)).pack(anchor='w',pady=8)
        ttk.Label(card,text='Closing this window leaves the server running. Use Stop server to stop collection delivery here.',style='Card.TLabel').pack(anchor='w')

    def _ai_tab(self,parent):
        card=ttk.Frame(parent,style='Card.TFrame',padding=20);card.pack(fill='both',expand=True)
        ttk.Label(card,text='Equipment identification',style='Title.TLabel').pack(anchor='w')
        ttk.Label(card,text='Local AI reads alarm messages/tags on this PC. Events use the machine tag entered at source registration, without AI. '
                  'Original logs stay unchanged. Equipment names are suggestions; unknown or ambiguous '
                  'machine assignments remain pending approval.',style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=8)
        ttk.Label(card,text='Suggested: an AI-proposed alarm name for review. Registered: an event uses the configured machine tag directly. '
                  'Event identification continues when alarm AI is disabled.',style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=4)
        ttk.Label(card,textvariable=self.ai_status,style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=8)
        bar=ttk.Frame(card,style='Card.TFrame');bar.pack(fill='x',pady=8)
        ttk.Label(bar,text='Installed Ollama model',style='Card.TLabel').pack(side='left')
        model=ttk.Entry(bar,textvariable=self.ai_model,width=22);model.pack(side='left',padx=8)
        self.controls.append((model,'normal'))
        self.button(bar,'Enable local AI',self.enable_machine_ai).pack(side='left')
        self.button(bar,'Disable',lambda:self._start('Disabling local AI...',self.service.disable_machine_ai,
                    lambda _:self.refresh_machine_ai())).pack(side='left',padx=8)
        self.button(bar,'Refresh interpretations',self.refresh_machine_ai).pack(side='left')
        columns=('Source','Table','Record ID','Identification','Equipment','Method / model')
        evidence=ttk.Frame(card,style='Card.TFrame');evidence.pack(side='bottom',fill='x',pady=(8,0))
        ttk.Label(evidence,text='Original message — select a result to compare it with the equipment name',style='Card.TLabel').pack(anchor='w')
        self.ai_evidence=tk.Text(evidence,height=3,wrap='word',state='disabled',font=('Segoe UI',10))
        evidence_scroll=ttk.Scrollbar(evidence,command=self.ai_evidence.yview)
        self.ai_evidence.configure(yscrollcommand=evidence_scroll.set)
        evidence_scroll.pack(side='right',fill='y');self.ai_evidence.pack(fill='x',expand=True)
        self.ai_tree=ttk.Treeview(card,columns=columns,show='headings')
        self.ai_tree.bind('<<TreeviewSelect>>',self.show_ai_evidence)
        for column,width in zip(columns,(180,120,80,120,260,140)):
            self.ai_tree.heading(column,text=column);self.ai_tree.column(column,width=width,minwidth=60)
        scroll=ttk.Scrollbar(card,command=self.ai_tree.yview)
        self.ai_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.ai_tree.pack(fill='both',expand=True)

    def show_ai_evidence(self,_=None):
        selection=self.ai_tree.selection()
        row=self.ai_rows.get(selection[0],{}) if selection else {}
        self.ai_evidence.configure(state='normal')
        self.ai_evidence.delete('1.0','end')
        self.ai_evidence.insert('1.0',row.get('original_message') or 'No original message available.')
        self.ai_evidence.configure(state='disabled')

    def enable_machine_ai(self):
        model=self.ai_model.get().strip()
        self._start('Checking the installed local AI model...',lambda:self.service.enable_machine_ai(model),
                    lambda _:self.refresh_machine_ai())

    def refresh_machine_ai(self):
        def shown(result):
            config=result['configuration'];self.ai_model.set(config['model'])
            self.ai_status.set(('Enabled' if config['enabled'] else 'Disabled')+
                ': '+config['model']+'. Suggestions are separate from saved record versions. Refresh to see background results.')
            children=self.ai_tree.get_children()
            if children:self.ai_tree.delete(*children)
            self.ai_rows={}
            self.show_ai_evidence()
            for row in result['rows']:
                labels=', '.join(dict.fromkeys(item['label'] for item in row['candidates']))
                key=self.ai_tree.insert('','end',values=(row['source_name'],row['source_table'],row['source_record_id'],
                    row['status'],labels or 'No verified suggestion',
                    'Registered machine tag' if row.get('policy_version')=='registered-event-machine-v1' else row['model'] or 'Not yet run'))
                self.ai_rows[key]=row
            self.status_text.set('Local AI interpretations refreshed. Collection and original logs are unchanged.')
        self._start('Reading local AI interpretation results...',self.service.machine_interpretations,shown)

    def _connection_tab(self,parent):
        card=self._scroll_card(parent)
        ttk.Label(card,text='Server connection and testing mode',style='Title.TLabel').pack(anchor='w',pady=(0,12))
        ttk.Label(card,text='Local testing keeps HTTPS on this PC. Network server accepts multiple collector PCs using the same central server hostname/IP below. Register each SCADA source and export its own collector setup.',style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=6)
        grid=ttk.Frame(card,style='Card.TFrame');grid.pack(fill='x')
        grid.columnconfigure(1,weight=1)
        ttk.Label(grid,text='Operating mode',style='Card.TLabel').grid(row=0,column=0,sticky='w',padx=(0,14),pady=5)
        box=ttk.Combobox(grid,textvariable=self.mode,values=tuple(MODES),state='readonly')
        box.grid(row=0,column=1,sticky='ew',pady=5);box.bind('<<ComboboxSelected>>',self._mode_changed)
        self.controls.append((box,'readonly'))
        for row,(title,var) in enumerate((('HTTPS listen IPv4 address',self.listen_address),('Central PC hostname / IPv4',self.server_host),('HTTPS port',self.https_port),('Server data folder',self.data_dir),('PostgreSQL 17 or 18 bin folder',self.postgres_bin),('Central database port (this PC only)',self.database_port)),start=1):
            ttk.Label(grid,text=title,style='Card.TLabel').grid(row=row,column=0,sticky='w',padx=(0,14),pady=5)
            entry=ttk.Entry(grid,textvariable=var);entry.grid(row=row,column=1,sticky='ew',pady=5)
            self.controls.append((entry,'normal'))
        ttk.Label(card,text='HTTPS listen address belongs to this server PC. The collector PC IP is not required here; collectors connect outward using the exported setup.',style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=6)
        ttk.Label(card,textvariable=self.url_preview,style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=10)
        self.button(card,'Save server settings',self.save_locations).pack(anchor='w',pady=8)
        ttk.Label(card,text='Stop the server before changing these settings, save, then start it. HTTPS certificates are generated for the saved hostname/IP. Export a fresh collector setup after changing the destination.',style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=6)
        ttk.Label(card,text='Network mode: use a stable LAN IP or DNS name. Allow the HTTPS TCP port through the server firewall for collector PCs. PostgreSQL remains on loopback. Firewall rules are not changed automatically.',style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=6)

    def _mode_changed(self,_=None):
        local=MODES[self.mode.get()]=='local'
        self.listen_address.set('127.0.0.1' if local else '0.0.0.0')
        if local:self.server_host.set('localhost')
        elif self.server_host.get()=='localhost':self.server_host.set('')
        self._preview_url()

    def _preview_url(self):
        self.url_preview.set('Collector upload URL: https://'+(self.server_host.get() or '<central PC hostname/IP>')+':'+self.https_port.get()+'/v1/uploads')

    def _settings_changed(self,*_):
        self._preview_url()
        self.status_text.set('Unsaved server settings. Stop the running server, save settings, then start it.')

    def _form_settings(self):
        return ServerSettings(Path(self.data_dir.get()),Path(self.postgres_bin.get()),int(self.database_port.get()),int(self.https_port.get()),
                              MODES[self.mode.get()],self.listen_address.get().strip(),self.server_host.get().strip().lower())

    def start_server(self):
        try:
            if self._form_settings()!=self.service.settings:
                raise CollectorError('Save the connection/mode settings before starting the server.')
        except (CollectorError,ValueError) as error:
            messagebox.showerror('Server settings',str(error),parent=self.root);return
        self._start('Starting the HTTPS API, database and worker...',self.service.start,self._started)

    def _registration_tab(self,parent):
        card=self._scroll_card(parent)
        ttk.Label(card,text='Register a SCADA database source',style='Title.TLabel').grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,12))
        card.columnconfigure(0,weight=1);card.columnconfigure(1,weight=1)
        self.boxes={}
        for index,name in enumerate(('customer','site','project','machine')):
            row=index*3+1
            ttk.Label(card,text='Existing '+name,style='Card.TLabel').grid(row=row,column=0,sticky='w')
            ttk.Label(card,text='New '+('machine tag' if name=='machine' else name+' name'),style='Card.TLabel').grid(row=row,column=1,sticky='w')
            box=ttk.Combobox(card,textvariable=self.choices[name],values=(NEW,),state='readonly',width=42)
            box.grid(row=row+1,column=0,sticky='ew',padx=(0,16),pady=(4,12))
            box.bind('<<ComboboxSelected>>',lambda _,key=name:self._cascade(key))
            self.boxes[name]=box;self.controls.append((box,'readonly'))
            entry=ttk.Entry(card,textvariable=self.names[name]);entry.grid(row=row+1,column=1,sticky='ew',pady=(4,12))
            self.controls.append((entry,'normal'))
        ttk.Label(card,text='SCADA PC / database source name',style='Card.TLabel').grid(row=13,column=0,columnspan=2,sticky='w')
        entry=ttk.Entry(card,textvariable=self.names['source']);entry.grid(row=14,column=0,columnspan=2,sticky='ew',pady=(4,10))
        self.controls.append((entry,'normal'))
        self.register_button=self.button(card,'Register source and generate IDs',self.register_source)
        self.register_button.grid(row=15,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Label(card,text='Registration creates the Source ID, Generation ID and protected upload credential. Database connection settings and collection schedules stay on the SCADA PC.',
                  style='Card.TLabel',wraplength=1000).grid(row=16,column=0,columnspan=2,sticky='w',pady=8)

    def _sources_tab(self,parent):
        card=ttk.Frame(parent,style='Card.TFrame',padding=20);card.pack(fill='both',expand=True)
        ttk.Label(card,text='Registered SCADA sources',style='Title.TLabel').pack(anchor='w',pady=(0,12))
        bottom=ttk.Frame(card,style='Card.TFrame');bottom.pack(side='bottom',fill='x')
        area=ttk.Frame(card,style='Card.TFrame');area.pack(fill='both',expand=True)
        columns=('Source','Customer','Site','Project','Source ID','Generation ID','Last received','Awaiting mapping')
        self.tree=ttk.Treeview(area,columns=columns,show='headings',selectmode='browse')
        for name,width in zip(columns,(180,120,110,130,280,280,190,150)):
            self.tree.heading(name,text=name);self.tree.column(name,width=width,minwidth=70,stretch=False)
        vertical=ttk.Scrollbar(area,command=self.tree.yview)
        horizontal=ttk.Scrollbar(area,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        area.rowconfigure(0,weight=1);area.columnconfigure(0,weight=1)
        self.tree.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        self.tree.bind('<<TreeviewSelect>>',self.selected)
        ttk.Label(bottom,textvariable=self.details,style='Card.TLabel',wraplength=1030).pack(anchor='w',pady=12)
        bar=ttk.Frame(bottom,style='Card.TFrame');bar.pack(fill='x')
        self.button(bar,'Export encrypted collector setup',self.export_dialog).pack(side='left')
        self.button(bar,'Create replacement upload credential',self.rotate).pack(side='left',padx=8)
        self.button(bar,'Refresh sources',self.refresh).pack(side='left')
        self.delete_button=self.button(bar,'Delete selected source',self.delete_source)
        self.delete_button.pack(side='right')
        ttk.Label(bottom,text='Copy the exported file to the SCADA PC, then choose Import server setup in the collector. Keep the file password separate.',
                  style='Card.TLabel',wraplength=1000).pack(anchor='w',pady=(12,0))

    def _scroll_card(self,parent):
        area=ttk.Frame(parent,style='Card.TFrame');area.pack(fill='both',expand=True)
        canvas=tk.Canvas(area,background='white',highlightthickness=0)
        scrollbar=ttk.Scrollbar(area,orient='vertical',command=canvas.yview)
        scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        card=ttk.Frame(canvas,style='Card.TFrame',padding=22)
        item=canvas.create_window((0,0),window=card,anchor='nw')
        card.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(item,width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        return card

    def _chosen(self,name):
        return self.choice_maps.get(name,{}).get(self.choices[name].get())

    def _cascade(self,changed=None):
        order=('customer','site','project','machine')
        start=order.index(changed)+1 if changed else 0
        tables=dict(customer='customers',site='sites',project='projects',machine='machines')
        for name in order[start:]:
            records=self.registry[tables[name]]
            for ancestor in order[:order.index(name)]:
                parent=self._chosen(ancestor)
                if parent is None:
                    records=[];break
                records=[row for row in records if row.get(ancestor+'_id')==parent[ancestor+'_id']]
            mapping={f"{row.get('machine_tag',row['name'])} [{row[name+'_id']}]":row for row in records}
            self.choice_maps[name]=mapping
            self.boxes[name].configure(values=(NEW,*mapping))
            self.choices[name].set(NEW)

    def _start(self,label,work,done):
        if self.busy:return False
        self.busy=True;self.status_text.set(label)
        self.progress.configure(mode='indeterminate')
        self.progress.start(12)
        for widget,_ in self.controls:widget.configure(state='disabled')
        def run():
            try:result=work()
            except CollectorError as error:self.pending.put((False,str(error),done))
            except Exception:self.pending.put((False,'Operation failed. Check the local server settings and private logs.',done))
            else:self.pending.put((True,result,done))
        threading.Thread(target=run,daemon=True,name='central-server-management').start()
        return True

    def _poll(self):
        try:success,result,done=self.pending.get_nowait()
        except queue.Empty:pass
        else:
            self.busy=False
            self.progress.stop()
            self.progress.configure(mode='determinate',value=0)
            for widget,state in self.controls:widget.configure(state=state)
            if success:done(result)
            else:
                self.status_text.set(result)
                if not self.closing:messagebox.showerror('Central Server',result,parent=self.root)
        if self.closing and not self.busy:
            self.root.destroy();return
        self.poll_id=self.root.after(80,self._poll)

    def _show(self,result,success_message=None):
        status=result['status']
        self.health_text.set(f"HTTPS API: {'Ready' if status['api_ready'] else 'Stopped'}   |   PostgreSQL: {'Ready' if status['database_ready'] else 'Stopped'}   |   Worker: {'Running' if status['worker_running'] else 'Stopped'}")
        self.metrics.set(f"Sources: {status['sources']}   Received batches: {status['batches']}   Saved record versions: {status['revisions']}\n"
                         f"Batches awaiting machine mapping: {status['quarantined_batches']}   Failed processing jobs: {status['failed_jobs']}")
        self.endpoint.set('Collector upload endpoint: '+status['upload_url'])
        settings=self.service.settings
        self.connection_summary.set(('Local testing: collectors on this PC only.' if settings.mode=='local' else 'Network server: collectors connect using '+settings.server_host+'.')+
                                    f' HTTPS listener: {settings.listen_address}:{settings.https_port}. Central PostgreSQL: this PC only.')
        self.registry=result['catalog'];self._cascade()
        self.source_rows={str(row['source_id']):row for row in result['sources']}
        selected=self.tree.selection()
        children=self.tree.get_children()
        if children:self.tree.delete(*children)
        for key,row in self.source_rows.items():
            self.tree.insert('', 'end', iid=key,values=(row['name'],row['customer_name'],row['site_name'],row['project_name'],key,str(row['generation_id'] or ''),str(row['last_received'] or 'No uploads'),row['quarantined_batches']))
        if selected and selected[0] in self.source_rows:self.tree.selection_set(selected[0])
        else:self.selected()
        self.status_text.set(success_message or status['error'] or 'Central Server status refreshed.')

    def refresh(self,success_message=None):
        def work():
            status=self.service.status()
            return dict(status=status,catalog=self.service.catalog() if status['database_ready'] else {k:[] for k in self.registry},sources=self.service.sources() if status['database_ready'] else [])
        self._start(success_message or 'Reading server health and registered sources...',work,
                    lambda result:self._show(result,success_message))

    def _started(self,_):
        self.refresh()

    def stop_server(self):
        if self.busy:return
        if messagebox.askyesno('Stop Central Server','Stop this local API, worker and central database? Collectors will retain pending uploads until the server starts again.',parent=self.root):
            self._start('Stopping local server components...',self.service.stop,self._started)

    def save_locations(self):
        if self.busy:return
        try:
            settings=self._form_settings()
        except (ValueError,CollectorError) as error:
            messagebox.showerror('Server settings',str(error),parent=self.root);return
        def saved(_):
            self.service=ManagerService(settings)
            self.refresh('Server settings saved successfully.')
        def persist():
            if settings != self.service.settings:
                status=self.service.status()
                if any(status[k] for k in ('database_ready','api_ready','worker_running')):
                    raise CollectorError('Stop the selected server before changing its mode, address, data folder or ports.')
            save_settings(settings)
        self._start('Saving local server locations...',persist,saved)

    def register_source(self):
        if self.busy:return
        values={}
        try:
            for name,key,label in (('customer','customer_name','customer name'),('site','site_name','site name'),
                                   ('project','project_name','project name'),('machine','machine_tag','machine tag'),
                                   ('source','source_name','SCADA PC/database source name')):
                row=self._chosen(name) if name!='source' else None
                if name!='source':values[name+'_id']=row[name+'_id'] if row else None
                values[key]=self.names[name].get()
                if row is None:
                    values[key]=text(values[key],label)
                    self.names[name].set(values[key])
        except CollectorError as error:
            self.status_text.set(str(error))
            messagebox.showerror('Registration settings',str(error),parent=self.root)
            return
        def registered(result):
            self.names['source'].set('')
            self.notebook.select(2)
            self.status_text.set('SCADA source registered. Refresh/select its row, then export the collector setup.')
            self.refresh()
        self._start('Registering the source and protecting its upload credential...',lambda:self.service.register(**values),registered)

    def _selected(self):
        selected=self.tree.selection()
        return self.source_rows.get(selected[0]) if selected else None

    def selected(self,_=None):
        row=self._selected()
        self.details.set(f"Source ID: {row['source_id']}\nGeneration ID: {row['generation_id']}\nSQL schema: {row.get('storage_schema') or 'Not available'}" if row else 'Select a source to export its collector setup.')

    def export_dialog(self):
        if self.busy:return
        try:
            if self._form_settings()!=self.service.settings:raise CollectorError('Save the connection/mode settings and start the server before exporting collector setup.')
        except (CollectorError,ValueError) as error:
            messagebox.showerror('Server settings',str(error),parent=self.root);return
        row=self._selected()
        if not row:
            messagebox.showinfo('Select source','Select a registered SCADA source first.',parent=self.root);return
        path=filedialog.asksaveasfilename(parent=self.root,title='Save encrypted collector setup',defaultextension='.linker-collector',
            initialfile='collector-'+str(row['source_id'])[:8]+'.linker-collector',filetypes=(('Encrypted collector setup','*.linker-collector'),))
        if not path:return
        window=tk.Toplevel(self.root);window.title('Protect collector setup');window.transient(self.root);window.grab_set()
        frame=ttk.Frame(window,padding=20);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Choose a file password of at least 12 characters.').pack(anchor='w')
        password=tk.StringVar(window);confirmation=tk.StringVar(window)
        for title,var in (('File password',password),('Confirm password',confirmation)):
            ttk.Label(frame,text=title).pack(anchor='w',pady=(10,4));ttk.Entry(frame,textvariable=var,show='*',width=45).pack(fill='x')
        def exported():
            value=password.get()
            if len(value)<12 or value!=confirmation.get():
                messagebox.showerror('File password','Enter matching passwords of at least 12 characters.',parent=window);return
            password.set('');confirmation.set('');window.destroy()
            self._start('Encrypting the selected collector setup...',lambda:self.service.export(row['source_id'],path,value),
                        lambda _:self.status_text.set('Encrypted setup exported. Import it locally in the collector; no database password or schedule was transferred.'))
        ttk.Button(frame,text='Export encrypted setup',command=exported).pack(anchor='e',pady=(14,0))

    def rotate(self):
        if self.busy:return
        row=self._selected()
        if row and messagebox.askyesno('Replacement upload credential','Create a replacement for this source? Existing credentials stay valid. Export and import the new setup to use the replacement.',parent=self.root):
            self._start('Creating a new protected upload credential...',lambda:self.service.rotate(row['source_id']),lambda _:self.status_text.set('Replacement credential created. Export an encrypted setup for this source.'))

    def delete_source(self):
        if self.busy:return
        row=self._selected()
        if not row:
            messagebox.showinfo('Select source','Select a registered SCADA source to delete.',parent=self.root);return
        message=(f"Delete SCADA source: {row['name']}?\n\n"
                 f"Customer: {row['customer_name']}\nSite: {row['site_name']}\nProject: {row['project_name']}\n"
                 f"Source ID: {row['source_id']}\n\n"
                 'This removes the registration from this list and revokes all its upload credentials. '
                 'Received records, mappings and audit history are retained. '
                 'Unsent batches remain on the collector and cannot upload using this registration.\n\n'
                 'This cannot be undone from this window. Continue?')
        if not messagebox.askyesno('Delete registered SCADA source',message,parent=self.root,icon='warning',default='no'):return
        self._start('Deleting the selected SCADA source registration...',lambda:self.service.delete_source(row['source_id']),
                    lambda _:self.refresh('SCADA source deleted. Upload credentials revoked; received history retained.'))

    def close(self):
        if self.busy:
            self.closing=True;self.status_text.set('Finishing the current operation before closing...');return
        try:dirty=self._form_settings()!=self.service.settings
        except ValueError:dirty=True
        if dirty and not messagebox.askyesno('Unsaved server settings','Discard unsaved connection/mode settings and close the window?',parent=self.root):return
        self.root.after_cancel(self.poll_id);self.root.destroy()


def launch():
    settings=load_settings()
    try:
        save_settings(settings)
    except CollectorError:
        pass  # Show the settings form even if PostgreSQL has not been installed.
    root=tk.Tk();ManagerWindow(root,ManagerService(settings));root.mainloop()
    return 0
