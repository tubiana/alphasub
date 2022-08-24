import pandas as pd
import datetime as dt
import numpy as np
import panel as pn
from panel.layout.gridstack import GridStack
import paramiko
import os
import io
from io import StringIO, BytesIO
from pathlib import Path
import param
import ipywidgets as ipw
from tkinter import Tk, filedialog
from glob import glob
#Import for graphs
import matplotlib
from matplotlib import cm
import plotly.express as px
import plotly.graph_objects as go
from panel_chemistry.pane import PDBeMolStar
import json
import sys



#Loading external extension HERE (example, ngl, ipywidgets, terminal, tabulator.......)
pn.extension('tabulator', 'terminal', 'ipywidgets','gridstack','plotly', sizing_mode = 'stretch_width', loading_spinner='dots')

pn.config.notifications = True # Panel notification System 





class Host():
    """
    This class will contain all tools and function related to server connectivity
    This will also be update to be used locally.

    Last thing, Paramiko for SSH connexion is very tricky to used.
    To be abble to use remote connexion throught a proxy it is necessary to create and use the sshconfig file.
    """
    
    def __init__(self):
        self.sshconfig = os.path.expanduser("~/.ssh/config")
        self.ssh = None
        self.node= None
        self.gpudf = None
        self.selectedgpu = None
        self.configJson = None
        self.multiGPU = False
        self.parameters = {}
        self.isconnected = False
        
        
        

        self.load_json()
        
        


    def connect(self):
        """
        Main function for connexion.
        """
        ssh_config = paramiko.SSHConfig() # Loading config module
        self.ssh = paramiko.SSHClient() # Loading SSHClient
        self.ssh.load_system_host_keys() # load present host keys
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy()) # Ignore warning when it's the first time connecting


        if os.path.isfile(self.sshconfig): #If the SSH config file is present.
            user_config_file = os.path.expanduser(self.sshconfig) #Replace '~' by the home user folder.
            with io.open(user_config_file, 'rt', encoding='utf-8') as f:
                ssh_config.parse(f)
            host_conf = ssh_config.lookup(self.parameters['serverName'])
            proxycommand = host_conf["proxycommand"]
            
        else: #If the ssh config is not present, try to used from the proxy command. Sploiler, doesn't work.
            user_config_file = None
            proxycommand =f"ssh -q {self.parameters['user']}@{self.parameters['proxyAddress']} nc {self.serverAddress}fr 22"

        
        if self.parameters["useProxy"] == True:
            sock = paramiko.ProxyCommand(proxycommand) #Configure the proxy.
            self.ssh.connect(self.parameters['serverName'], username=self.parameters['user'], password=self.parameters['password'], sock=sock)
        else:
            self.ssh.connect(self.parameters['serverName'], username=self.parameters['user'], password=self.parameters['password'])
        self.sshChanel = self.ssh.invoke_shell()


    def create_config_file(self):
        """
        This function is to parametrise and create the .ssh/config file if it does not exist yet.
        """
        if self.parameters["user"] == "":
            print("Warning - No user set ed up.")
            return #To be tested.
        hoststring = f"""Host {self.parameters['serverName']}
    User {self.parameters["user"]}
    ProxyCommand ssh -q {self.parameters["user"]}@passerelle.i2bc.paris-saclay.fr nc {self.parameters['server']} %p
    ServerAliveInterval 60\n"""
        #Check if .ssh folder exist
        if not os.path.isdir("~/.ssh"):
            os.makedirs("~/.ssh")

        if not os.path.isfile(self.sshconfig):
            with open(self.sshconfig, "w+") as filout:
                filout.write(hoststring)
        else:
            if not f"Host {self.parameters['serverName']}" in open(self.sshconfig).read():
                with open(self.sshconfig, "a") as filout:
                    filout.write(hoststring)
        


    def add_key_in_authorized_keys(self):
        ssh_stdin, ssh_stdout, ssh_stderr = self.ssh.exec_command("""
# Test if .ssh directory exist
SSHDIR=~/.ssh
if [ ! -d "$SSHDIR" ]; then
    mkdir $SSHDIR
fi

#Test if rsa file exist, otherwise create it
RSAFILE=~/.ssh/id_rsa
if [ ! -f "$RSAFILE" ]; then
    ssh-keygen -t rsa -f $RSAFILE -q -P ""
fi

#Test if Authorized_keys exist
KEYSFILE=~/.ssh/authorized_keys
if [ ! -f "$KEYSFILE" ]; then
    touch $KEYSFILE
fi

#Check if the ID_RSA is already in the authorized_keys file
rsakey=$(cat $RSAFILE.pub)
if ! grep -Fxq "$rsakey" $KEYSFILE
then
    echo "$rsakey" >> $KEYSFILE
fi
""")

    def check_gpu_usage(self):
        nvidiasmi_command = "nvidia-smi --query-gpu=timestamp,name,temperature.gpu,utilization.gpu,utilization.memory,memory.total,memory.free,memory.used --format=csv"
        if self.parameters['serverName'].lower() == "cluster-i2bc":
            fullcommand = f"ssh node{self.node} {nvidiasmi_command}"
        else:
            fullcommand = f"{nvidiasmi_command}"
        ssh_stdin, ssh_stdout, ssh_stderr = self.ssh.exec_command(fullcommand)
        results = ssh_stdout.read().decode()
        csv = StringIO(results)
        self.gpudf = pd.read_csv(csv)
        self.gpudf["utilisation.gpu (%)"] = self.gpudf[' utilization.gpu [%]'].str.extract(r'(\d+)')
        self.gpudf["utilisation.mem (%)"] = self.gpudf[' utilization.memory [%]'].str.extract(r'(\d+)')
        self.gpudf["total memory (MiB)"] = self.gpudf[' memory.total [MiB]'].str.extract(r'(\d+)')
        self.gpudf["Free memory (MiB)"] = self.gpudf[' memory.free [MiB]'].str.extract(r'(\d+)')
        self.gpudf["Used Memory (MiB)"] = self.gpudf[' memory.used [MiB]'].str.extract(r'(\d+)')

        self.gpudf["utilisation.gpu (%)"]  = self.gpudf["utilisation.gpu (%)"].astype(float)
        self.gpudf["utilisation.mem (%)"]  = self.gpudf["utilisation.mem (%)"].astype(float)
        self.gpudf["total memory (MiB)"]  = self.gpudf["total memory (MiB)"].astype(int)
        self.gpudf["Free memory (MiB)"]  = self.gpudf["Free memory (MiB)"].astype(int)
        self.gpudf["Used Memory (MiB)"]  = self.gpudf["Used Memory (MiB)"].astype(int)
        
        #self.gpudf = self.gpudf[[" name","utilisation.gpu (%)","utilisation.mem (%)", "total memory (MiB)","Free memory (MiB)","Used Memory (MiB)"]]
        self.gpudf = self.gpudf[[" name", "total memory (MiB)", "Used Memory (MiB)"]]
        
        
    def update_parameters_tab(self, event):
        activeTabid = self.hostTab.active    
        activeTab = self.hostTab[activeTabid]
        serverName = self.hostTab._names[activeTabid]
        serverAddress = self.configJson[serverName]['server']

        def add_in_dict(items, newparameters):
            
            for obj in items:
                if obj.name != None:
                    try:
                        newparameters[obj.name] = obj.value
                    except:
                        add_in_dict(obj, newparameters)
                elif hasattr(obj, "objects"):
                    add_in_dict(obj, newparameters)
                else:
                    print("unknown item in tabs")
            return newparameters

        newparameters = {"serverName":serverName}
        newparameters["server"] = serverAddress


        newparameters = add_in_dict(activeTab, newparameters)

        selectedNode = self.find_object_in_tab(activeTab, "Node")
        if selectedNode != None:
            self.node = int(selectedNode.value[:2])

            
        self.parameters = newparameters


        
    def select_gpu(self):
        freegpu = list(self.gpudf.query("`Used Memory (MiB)` < 120 ").index)
        if len(freegpu) == 0:
            self.selectedgpu = -1
        else:
            self.selectedgpu = freegpu[-1]

        currentTab  = self.hostTab[self.hostTab.active]

        dfGPU, index = self.find_layout_in_tab(currentTab, "dataFrameGPUCARD")
        if index == None: #New tabs to add.
            index = -2
            GPUdfPanel = pn.widgets.Tabulator(self.gpudf, name="dataFrameGPU")
            GPUdfPanel.style.apply(lambda x: ['background: lightgreen' if x.name in [self.selectedgpu] else '' for i in x], axis=1)
            self.hostTab[self.hostTab.active].insert(index, pn.Card(GPUdfPanel, name="dataFrameGPUCARD", title="GPU INFO"))
        else:
            self.hostTab[self.hostTab.active].pop(index)

            GPUdfPanel = pn.widgets.Tabulator(self.gpudf, name="dataFrameGPU")
            GPUdfPanel.style.apply(lambda x: ['background: lightgreen' if x.name in [self.selectedgpu] else '' for i in x], axis=1)
            self.hostTab[self.hostTab.active].insert(index, pn.Card(GPUdfPanel, name="dataFrameGPUCARD", title="GPU INFO"))

        gpuWidget = self.find_object_in_tab(currentTab, "GPUID")

        gpuWidget.value=self.selectedgpu

        return None

        
        

    def define_PBSlines(self):
        self.PBSlines = f"""#PBS -l select=1:ncpus=8:host=node{self.node}:ngpus=1
#PBS -q cryoem"""


    def find_object_in_tab(self, panel, name):
        if hasattr(panel, "objects"): #This is a panel with objets inside
            for object in panel.objects:
                match =  self.find_object_in_tab(object, name)
                if match is not None:
                    return match
        else:
            if hasattr(panel, "name"):
                if panel.name == name:
                    return panel
                else:
                    return None
            else:
                return None    

    def find_layout_in_tab(self, panel, name):
        
        if hasattr(panel, "objects"): #This is a panel with objets inside
            for i,object in enumerate(panel.objects):
                if object.name == name:
                    return object, i
        #If nothing was found
        return (None, None)



    def init_connect(self): 
        #Put loading
        self.hostTab.loading=True

        selectedTab = self.hostTab._names[self.hostTab.active]

        #1. Create host config file 
        self.create_config_file()

        #2 Connect to SSH to the I2BC cluster
        self.connect()
        self.write_terminal("\nConnected\n")

        #3. prepare connexion to node
        self.add_key_in_authorized_keys()

        #4. check GPU usage
        self.check_gpu_usage()

        #4. Find available GPU
        self.select_gpu()
        self.define_PBSlines()
        self.hostTab.loading=False

        
        pn.state.notifications.success("Connexion established", 2000)
        self.isconnected = True
        statusPanel = self.find_object_in_tab(self.hostTab[self.hostTab.active], "status")
        statusPanel.value = True
        
        self.run_command('host=`hostname`; echo "connected to $host"')
        
        
        #self.p1.append(self.GPUdfPanel)
    
    def create_tabs_from_config(self):

        #Function for 2 lines because i'm lazy
        def set_value_and_add(col, panel, param, label):
            #This is needed to link the value between clones and original one.
            value= param[label]
            temp = panel.clone(name=label)
            temp.value = value            

            col.append(temp)

        #This will contains all tabs,
        tabs = pn.Tabs()

        for server in self.configJson.keys():
            
            col = pn.Column(name=str(server))
            
            params = self.configJson[server]
            if params["passerelle"] != "":
                col.append(self.useProxyPanel.clone(name="useProxy", value=True))
                col.append(pn.widgets.TextInput(name="proxyAddress", value=params["passerelle"]))

               
            col.append(self.passwordPanel.clone(name="password"))
            col.append(self.userPanel.clone(name="user", value=params["user"]))

            col.append(self.hostWorkdir.clone(name="workdir"))
            if "nodes" in params:
                self.nodePanel.options = params["nodes"]
                if params["NGPU"] > 1 :
                    col.append(pn.Row(
                        self.nodePanel.clone(name="Node"), 
                        pn.widgets.Select(name="GPUID", options=list(range(params["NGPU"])))))
            else:
                if params["NGPU"] > 1:
                #Adding choice of GPU
                    col.append(pn.widgets.Select(name="GPUID", options=list(range(params["NGPU"]))))


            set_value_and_add(col, self.singularityImage, params, "singularityImage")
            set_value_and_add(col, self.databaseFolder, params, "databaseFolder")
            set_value_and_add(col, self.paramsFolder, params, "paramsFolder")
            #if params["multipleGPU"] == True:
            #    col.append(self.accordeonDataFrame.clone(name="dataFrameCard"))
            #col.append(sqelf.gpu)

            if str(server) != "local":
                col.append(self.RUNBUTTON)
                col.append(pn.Row(pn.widgets.StaticText(value="Connexion Statut"), self.statusPanel.clone(name="status")),)

            tabs.append(col)


        return tabs
            
            
    def load_json(self, json_path = "~/.alphasub/servers.json"):
        json_path = os.path.expanduser(json_path) #Replace ~ by userfolder
        if not os.path.isfile(json_path):
            try:
                os.makedirs(os.path.expanduser("~/.alphasub"))
            except FileExistsError:
                pass #The directory 
            config = {"local":{
                        "passerelle":"",
                        "server":"",
                        "port":22,
                        "user":"default",
                        "databaseFolder" : "",
                        "singularityImage": "",
                        "paramsFolder": "",
                        "executor": "bash",
                        "NGPU":1,
                            }
                        }
            with open(json_path,'w') as json_file:
                json.dump(config, json_file)
                self.configJson = config
            return 0
        #From there the file json_path exist
        with open(json_path, "r") as json_file:
            self.configJson = json.load(json_file)
            return 1



    def init_panels(self):
        #GENERAL
        self.passwordPanel = pn.widgets.PasswordInput(name="Password",placeholder="Password (not mandatory if ssh configured)")
        self.userPanel = pn.widgets.TextInput(name="Username",placeholder="Username")
        self.useProxyPanel = pn.widgets.Toggle(name="Use passerelle?",button_type="primary", value=True)
        self.statusPanel = pn.indicators.BooleanStatus(value=False, color="success")
        self.RUNBUTTON = pn.widgets.Button(name="Connection", button_type="primary")
        self.singularityImage = pn.widgets.TextInput(name="Singularity image", placeholder="Path to Singularity Image", value="/data/work/I2BC/thibault.tubiana/alphafold/container/colabfold280422.sif")
        self.databaseFolder = pn.widgets.TextInput(name="Database location", placeholder="Path to database folder", value="/data/work/I2BC/pa.charbit/colabfold/database/uniref30_2103")
        self.paramsFolder = pn.widgets.TextInput(name="Database location", placeholder="Path to database folder", value="/data/work/I2BC/thibault.tubiana/alphafold/params")
        self.hostWorkdir = pn.widgets.TextInput(name="Host WORKDIR", placeholder="Path to host workdir", value="/home/thibault.tubiana/work/alphasub/test")
        

        #ClusterI2BC Only
        self.nodePanel = pn.widgets.Select(name="Node", options=["38 (GTX1080Ti)","39 (RTX2080TI"])
        self.gpuPanel  = pn.widgets.Select(name = "GPUID", options=list(range(8)))       

        #    table with GPU
        self.GPUdfPanel = pn.widgets.Tabulator(name="gpuDfWidget",sizing_mode="stretch_width", max_width=385)
        #self.accordeonDataFrame = pn.Card(self.GPUdfPanel, name='gpuDfCard', title="GPU Information", collapsed=True, sizing_mode='stretch_height', max_width=385)



        #Run button
        
        self.RUNBUTTON.on_click(self.update_parameter_and_run)

        self.hostTab = self.create_tabs_from_config()
        #Add watcher to HostTab to update internal parameters dict everytime a tab is changed.
        self.hostTab.param.watch(self.update_parameters_tab, "active")
        
        self.terminal = pn.widgets.Terminal(
    "This terminal will contain output from Alphafold Jobs",
    options={"cursorBlink": True},
    sizing_mode='stretch_height'
)
        self.terminalLayout = pn.Card(self.terminal, title="Terminal", collapsible=False)

        self.remotePath = pn.widgets.TextInput(name='Remote server', placeholder="Absolute path in remove server")
        


    def write_terminal(self, str):
        self.terminal.write(str)

    def run_command(self, cmd, cd=None):
        if cd != None:
            cmd = f"cd {cd}; {cmd}"


        stdin, stdout, stderr = self.ssh.exec_command(cmd)

        out = stdout.read().decode()
        err = stderr.read().decode()
        self.terminal.write(out+"\n"+err)
        return stdout.channel.recv_exit_status()        


    def update_parameter_and_run(self, event):
        #Update node number
        self.node = int(self.nodePanel.value[:2])
        # activetabID = self.hostTab.active
        # tabname = self.hostTab._names[activetabID]
        # self.parameters['serverName'] = tabname
        
        self.update_parameters_tab(None)


        self.init_connect()

        


class Alphafold():
    """
    Class for all parameters for alphafold.
    Underlines respects the PARAM methodology to instance parameters.
    """



    def __init__(self, sshInstance):


        #Parameters
        self.HOST = sshInstance
        self.mode = "query" # Could be query, fasta, a3m

        # MMSEQ
        # Positional arguments
        
        self.query = pn.widgets.TextAreaInput(name="Input sequence", placeholder="paste your sequence(s) here", sizing_mode='stretch_height')
        self.jobname = pn.widgets.TextInput(name = "Jobname", placeholder="It will be the name of your sequence")
        self.localDir = pn.widgets.TextInput(name = "local directory", placeholder="Results will be saved here")
        self.modelVersion = pn.widgets.Select(name="Alphafold Version", options=["auto","AlphaFold2-ptm","AlphaFold2-multimer-v2"])
        
        # Uploading
        self.fastaFile = pn.widgets.FileInput(accept='.fasta', multiple=False)
        self.msasFile = pn.widgets.FileInput(accept='.a3m', multiple=True)

        self.dbbase = pn.widgets.TextInput(name = "database location", placeholder="Please write VALID path do database folder", value="/data/work/I2BC/pa.charbit/colabfold/database")
        self.base = pn.widgets.TextInput(name = "Directory for the results (in the cluster)", placeholder="Please write VALID path do database folder")


        self.sensitivity = pn.widgets.IntSlider(name="Sensitivity", start=1, end=10, step=1, value=8)
        self.sensitivityLayout = pn.Column(self.sensitivity, 
                                           pn.widgets.StaticText(name="*Lowering this will result in a much faster search but possibly sparser msas*", style={'font-style':'italic'})
                                           )

        

        
        self.db1 = pn.widgets.Select(name="DB1 (Sequence database)",options=["uniref30_2103_db"])
        self.db2 = pn.widgets.TextInput(name="DB2 (Template database)",placeholder="Path to Template Database (OFF)", disabled=True)
        self.db3 = pn.widgets.Select(options=["colabfold_envdb_202108_db"],name="DB3 (metagenomic database)", disabled=True)
        self.use_env = pn.widgets.Checkbox(name="Use environmental (metagenomic) database", value=False, disabled=False)
        self.use_template = pn.widgets.Checkbox(name="Use Template database", value=False, disabled=True)
        
        self.filter = pn.widgets.Checkbox(name="Use filter", value=True)
        self.mmseqs = pn.widgets.TextInput(name="MMSeqs folder location", placeholder = "Please indicate a VALID path", value="/data/work/I2BC/pa.charbit/colabfold/program/", disabled=True)
        self.expand_eval = pn.widgets.TextInput(name="expand-eval (??)", value="inf")
        self.align_eval = pn.widgets.IntInput(name="align-eval (??)", value=10)
        self.diff = pn.widgets.Checkbox(name="DIFF: Keep only most diverse", value=False)
        self.qsc = pn.widgets.FloatInput(name="threshold for the DIFF filterting", value=-20,)
        self.max_accept = pn.widgets.IntInput(name="max-accept (Maximum number of alignment results per query sequence)", value=10)
        self.db_load_mode = pn.widgets.Select(name ="db_load_mode", options={"fread (3)":3,"mmap (2)":2}, value=3)

        self.useOwnAlignment = pn.widgets.CheckButtonGroup(name="Use our own alignment", options=["Use my own alignment"], button_type='success')
        self.chooseAlignmentFile = pn.widgets.Button(name="Select alignment", button_type = 'light', height=25)
        self.chooseAlignmentFile.on_click(self.select_files)
        self.alignmentFile = pn.widgets.StaticText(value="")
        self.DOALIGNMENT = pn.widgets.Checkbox(name="Produce alignment", value=True)
        
        #self.alignmentFile = pn.widgets.FileInput(name="Fasta/a3m file", accept='fasta,a3m', multiple=False, visible=False)
        #Link visibility status of alignmentFile with the button useOwnAlignment
        #self.useOwnAlignment.link(self.alignmentFile, value='visible')
        
        self.alignmentFileRow = pn.Row(self.chooseAlignmentFile, self.alignmentFile, visible=False)

        # AlphaFold 
        self.Nmodels = pn.widgets.IntInput(name="Number of models",value=5, start=1, end=5)
        self.use_amber = pn.widgets.Checkbox(name="Relax model (with Amber)", value=True)
        self.DOMODELS = pn.widgets.Checkbox(name="Produce models", value=True)
        self.use_gpu_amber = pn.widgets.Checkbox(name="Use GPU for minimisation", value=True, disabled=True)
        self.nmer = pn.widgets.IntInput(name="Number of oligomer", value=1, start=1, end=6)
        


        #Watcher
        def change_statut_gpuAmber(event):
            self.use_gpu_amber.disabled = not self.use_amber.value
        self.use_amber.param.watch(change_statut_gpuAmber, 'value')

        self.NumRecycle = pn.widgets.IntSlider(name="Number of recycle", start=0, end=12, step=3, value=3)

        #Control widgets
        self.GOGOGO = pn.widgets.Button(name="GOGOGO", button_type='danger')

        #DEBUG
        self.editor = pn.widgets.Ace(value="", sizing_mode='stretch_both', language='sh', height=800, visible=False)


        self.querybox = pn.Tabs(("Query sequence", self.query))
        self.querybox.append(("Multiple Sequence", pn.Column(
                                        pn.pane.Markdown("""
                                        Note: This fasta uploading tool is dedicated to fasta with multiple query sequences **WITHOUT** multiple sequence alignement.  
                                        Example:
                                        ```fasta
                                        >SEQ1
                                        MCQPKVSKPL
                                        >SEQ2
                                        MQSLKDNHGFVY
                                        ```
                                        """),
                                        self.fastaFile
                                        )
        ))
        self.querybox.append(("Multiple Sequence Alignment",pn.Column(
                                        pn.pane.Markdown("""
                                        This q3m uploading tool is dedicated to A3M files with multiple sequence alignment already made (by MMSEQS for example).  
                                        Usefull if you want to just do re-modelling.. 
                                        """),
                                        self.msasFile
                                        )
                                        )
                                )
        
        #prepare layout
        self.msaBasics = pn.Column(self.DOALIGNMENT,
                                    self.querybox, 
                                    self.jobname, 
                                    # self.localDir,
                                    # self.useOwnAlignment,
                                    # self.alignmentFileRow, 
                                    # self.base, 
                                    # self.dbbase,

          )
        self.msaAdvanced = pn.Card(self.sensitivityLayout,
                                         self.db1, self.db2, self.db3,
                                         self.use_env,
                                         self.use_template,
                                         self.filter,
                                         self.mmseqs,
                                         self.expand_eval,
                                         self.align_eval,
                                         self.diff,
                                         self.qsc,
                                         self.max_accept,
                                         self.db_load_mode,
                                         title="Advanced parameters",
                                         collapsed =True,
                                         )
        self.msaTab = pn.Column(self.msaBasics, self.msaAdvanced)

        self.modelBasics = pn.Column(
            self.DOMODELS,
            self.Nmodels, 
            self.modelVersion, 
            pn.Row(self.use_amber, self.use_gpu_amber),
            self.NumRecycle,
            self.nmer,
        )
        self.modelAdvanced = pn.Card(title="Advanced parameters", collapsed =True)
        self.modelTab = pn.Column(self.modelBasics, self.modelAdvanced)
    
        #WATCHER
        self.useOwnAlignment.param.watch(self.show_file_button, ['value'])
        self.GOGOGO.on_click(self.run_alphafold)
        self.fastaFile.param.watch(self.update_fileUpload, ['filename'])
        self.msasFile.param.watch(self.update_fileUpload, ['filename'])

    
    def select_files(self, *b):
        root = Tk()
        root.withdraw()                                        
        root.call('wm', 'attributes', '.', '-topmost', True)   
        self.chooseAlignmentFile.disabled=True
        self.alignmentFile.value = filedialog.askopenfilename(multiple=False) 
        self.chooseAlignmentFile.disabled=False
        self.update_on_fileSelector()


    def update_fileUpload(self, event):
        filename=event.new
        #If string it means it's a single fasta file
        if isinstance(filename, str):
            basename = '.'.join(filename.split(".")[:-1])
            extension = filename.split(".")[-1]
            self.DOALIGNMENT.value = True
            self.DOALIGNMENT.disabled = False

        #If list it could be multiple A3M files.
        elif isinstance(filename, list):
            basename = '.'.join(filename[0].split(".")[:-1])
            extension = "a3m"
            self.DOALIGNMENT.value = False
            self.DOALIGNMENT.disabled = True

        
        self.jobname.value=basename
        if extension.lower() == "fasta":
            self.mode = "fasta"
        elif extension.lower() == "a3m":
            self.mode = "a3m"
        

    
    def update_on_fileSelector(self):
        from pathlib import Path
        file = self.alignmentFile.value

        filename = Path(file).stem
        folder = str(Path(file).parent.absolute())
        self.localDir.value = folder
        self.jobname.value = filename


    
    def show_file_button(self, *events):
        if len(self.useOwnAlignment.value) == 0:
            # self.alignmentFile.visible = False
            self.alignmentFileRow.visible=False
            # self.query.disabled=False
            # self.jobname.disabled = False
            # self.localDir.disabled = False
        else:
            # self.alignmentFile.visible = Tru
            # self.query.disabled=True
            # self.jobname.disabled = True
            # self.localDir.disabled = True
            self.alignmentFileRow.visible=True
            
    def run_command(self, cmd, cd=None):
        if cd != None:
            cmd = f"cd {cd}; {cmd}"


        stdin, stdout, stderr = self.HOST.ssh.exec_command(cmd)

        out = stdout.read().decode()
        err = stderr.read().decode()
        self.HOST.terminal.write(out+"\n"+err)
        return stdout.channel.recv_exit_status()


    def run_alphafold(self, *b):

        # Clear notifications.
        pn.state.notifications.clear()


        # Check connectivity
        if self.HOST.statusPanel.value == False:
            pn.state.notifications.error("No connexion to host", duration=0)
            return 0

        #Generate the script to be coppy into the host
        self.generate_script()


        self.editor.visible=True #This is for debuging

        # Check Connexion
        workdir = self.HOST.hostWorkdir.value
        if workdir == "":
            pn.state.notifications.error("Host ouput dir is empty. Please check again", duration=0)
            return 0

        #Check Connectivity: 
        outcode = self.run_command(f'mkdir -p {workdir}; cd {workdir}')
        print(workdir)
        if outcode != 0:
            pn.state.notifications.error("Cannot create output directory. Please check terminal output", duration=0)
            return 0

        #Create the script
        ftp = self.HOST.ssh.open_sftp()
        ftp.chdir(workdir)
        #Write script
        ftp.putfo(BytesIO(self.script.encode()), "run_pred.sh")
        

        #self.run_command(f'echo "{self.script}" > run_pred.sh')

        #Create the fasta file
        if self.mode == "query":
            if not self.query.value.startswith(">"):
                content = f">{self.jobname.value}\n{self.query.value}"
            else:
                content = f"{self.query.value}"
            ftp.putfo(BytesIO(content.encode()), f"{self.jobname.value}.fasta")

        elif self.mode == "fasta":
            content = self.fastaFile.value.decode("utf-8")
            ftp.putfo(BytesIO(content.encode()), self.jobname.value+".fasta")

        elif self.mode == "a3m":
            self.run_command(f'pwd; mkdir {workdir}/msas')
            for i in range(len(self.msasFile.value)):
                content = self.msasFile.value[i]
                name = self.msasFile.filename[i]
                name = name.replace(" ","_").replace("'","")
                ftp.putfo(BytesIO(content), f"msas/{name}")

        
        
        if self.DOALIGNMENT.value == True or self.DOMODELS.value == True:
            self.run_command(f"{self.HOST.executor} run_pred.sh", cd=workdir)
            pn.state.notifications.success("job submitted")
        else:
            pn.state.notifications.info("Files created but not submeted since alignments and models are deactivated")

        

    def convert_parameters(self, p):
        """
        Convert parameter for bash command line.
        Example, bool True should be 1, bool False should be 0..
        """

        #Bool
        if isinstance(p, bool):
            conversion = {True:1,False:0}
            return conversion[p]
        if isinstance(p, list):
            conversion = {"fread (3)":3,
                          "mmap (2)":2}
            return conversion[p]

    def generate_script(self):

        if self.use_amber.value == True:
            if self.use_gpu_amber.value:
                minimisationString = "--amber --use-gpu-relax"
            else:
                minimisationString = "--amber"
        else:
            minimisationString = ""

        script = f"""#!/bin/bash
{self.HOST.PBSlines}

# 1. ===== PARAMETER SETINGS <- NEED TO BE MODIFY AT EVERYRUN ========
FASTA_FILE="{self.jobname.value}".fasta #FASTA NAME

FASTA_DIR="{self.HOST.hostWorkdir.value}" #DIRECTORY OF THE FASTA FILE

#  Default Options. Change it if you want :-) 
MODELTYPE="{self.modelVersion.value}" #COULD BE AlphaFold2-multimer-v1, AlphaFold2-multimer-v2, AlphaFold2-ptm, auto
MINIMISATION="{minimisationString}" # COMMENT To remove minimisation
NMER={self.nmer} #Number of MERS, 2 for DIMERS (symetrical), 3 for Trimers..... /!\ IT IS DIFFERENT FROM MULTIMERS WITH 2 SEQUENCES SEPARATED BY ':'
NUMRECYCLE={self.NumRecycle.value} #Number of recycling of each model. should be 3 at minimum to improve a bit models.

DBLOADMODE={self.db_load_mode.value} #3 = faster reading but do not take advantage of cached files. 2 is faster when the databse is already in the memory.
USEENV={self.convert_parameters(self.use_env.value)} # 0 = do not use environmental database, 1=Use environmentale databse. 

DOALIGNMENT={"true" if self.DOALIGNMENT.value else "false"} # Comment or set to false if you already have a folder called "msas" with an a3m MSA inside.
DOMODELS={"true" if self.DOMODELS.value else "false"} # Comment or set to false if you don't want to make the models (only generate MSAS)
GPUINDEX={self.HOST.gpuPanel.value} #For multiGPU nodes, select only the GPU 0. Change to your favourite GPU number!


# 2. ===== other parameters, don't change if except if you know what you are doing :-) 
MSA_DIR=${{FASTA_DIR}}/msas #FOLDER THAT WILL CONTAIN THE MSA
PRED_DIR=${{FASTA_DIR}}/predictions #FOLDER THAT WILL CONTAIN PREDICTIONS
PARAMS_DIR={self.HOST.paramsFolder.value}
DATABASES={self.HOST.databaseFolder.value}
IMAGESINGULARITY={self.HOST.singularityImage.value} #LOCATION OF THE SINGULARITY IMAGE

# 3. ==== Creation of the output dir in the $FASTA_DIR
mkdir -p ${{FASTA_DIR}} &> /dev/null
mkdir -p ${{MSA_DIR}} &> /dev/null
mkdir -p ${{PRED_DIR}} &> /dev/null

# 4. ==== PREPARATION OF THE SINGULARITY COMMAND
#     Note :  -B are mounting point to link folder on the host machine to the singularity container.
SINGULARITYCOMAND="singularity exec \
 -B ${{DATABASES}}:/alpha/database\
 -B ${{FASTA_DIR}}:/inout/fasta\
 -B ${{PARAMS_DIR}}:/opt/cache\
 -B ${{MSA_DIR}}:/inout/msas -B ${{PRED_DIR}}:/inout/predictions --nv ${{IMAGESINGULARITY}}"

cd $FASTA_DIR



if [ "$DOALIGNMENT" == true ]; then
    echo "-- Doing alignment with MMSEQS --"
    touch searchingSequences
    $SINGULARITYCOMAND\\
    colabfold_search -s {self.sensitivity.value} \\
    --db1 {self.db1.value} \\
    --db3 colabfold_envdb_202108_db \\
    --use-env ${{USEENV}} \\
    --use-templates {self.convert_parameters(self.use_template.value)} \\
    --filter {self.convert_parameters(self.filter.value)} \
    --expand-eval {self.expand_eval.value} \\
    --align-eval {self.align_eval.value} \\
    --diff {self.convert_parameters(self.diff.value)} \\
    --qsc {self.qsc.value} \\
    --max-accept {self.max_accept.value} \\
    --db-load-mode ${{DBLOADMODE}} \\
    /inout/fasta/${{FASTA_FILE}} /alpha/database/ /inout/msas > outalign.txt 2>&1

    rm searchingSequences
    touch searchingSequencesDone

    cd msas
    echo "Renaming A3M files"
  for file in `ls *.a3m`; do
  filename=`python3 <<EOF
input = open("$file", 'r')
while input:
    line=input.readline()
    if line.startswith('>'):
        name=line.replace('>','').strip().split('\\t')[0]
        print(name)
        break
EOF
`
  echo $filename
    mv $file "${{filename}}.a3m"
  done
  cd ..
fi

#Replace the models to have NMERS (per default : 1)
for file in `ls msas/*.a3m`;
  do
  echo $file
  sed -i -E "s|(#[0-9]*\t)[0-9]+|\1$NMER|g" $file
done


if [ "$DOMODELS" == true ]; then
  echo "-- Doing models --"
  touch makingModels
  CUDA_VISIBLE_DEVICES=$GPUINDEX $SINGULARITYCOMAND colabfold_batch --model-type ${{MODELTYPE}} $MINIMISATION --num-recycle $NUMRECYCLE /inout/msas /inout/predictions
  rm makingModels
  touch makingModelsDone
  
  cd predictions
  NSEQS=`ls -l *.a3m | wc -l` 
  #put each models into a subdirectory if there are several models made.
  if [ $NSEQS -gt 1 ]; then
    for file in `ls *.a3m`; do
      seq=`basename -s .a3m $file`
      mkdir $seq >/dev/null 2>&1
      mv $seq* $seq >/dev/null 2>&1
    done
  fi
  cd ..
fi
"""
        self.script = script
        self.editor.value=script
        self.editor.width=800
        
        

class Results():
    """Class that will contain all results widgets"""
    def __init__(self, host):
        self.widgets = pn.Card(title="Results", collapsible=False)
        self.HOST = host
        self.workdir = "/Users/thibault/Library/CloudStorage/OneDrive-Personal/Work/Postdoc/CNRS2022/projects/HCV/alphafold/construct_NS5A_single/"
        # self.workdir = "/mnt/c/Users/tubia/OneDrive/Work/Postdoc/CNRS2022/projects/HCV/alphafold/construct_NS5A_single/"
        # self.workdir = "/mnt/c/Users/tubia/OneDrive/Work/Postdoc/CNRS2022/projects/noro/NS4_dim"
        #self.workdir = "/Users/thibault/cnrs2022/projects/noro/NS4_dim"

        self.mainLayout = pn.Column()
        self.jobs = []
        self.tabs_index = {}
        self.jobsTabs = None
        self.modelsMenus = []
        self.PAEGraphsList = [] 
        self.molstar = None#PDBeMolStar(height=500, sizing_mode='stretch_width',)
        self.molstarLayout = []

        
        
        # self.load_results()



    def load_results(self):
        self.find_models()
        self.create_tabs()
        self.mainLayout.append(pn.WidgetBox(self.jobsTabs))

        #Add watcher to update tabs
        self.jobsTabs.param.watch(self.update_tabs, "active")
        self.update_graph(None)
        
        #self.load_graph(self.jobsTabs.active)


    def update_tabs(self, even):
        # self.clear_tab(self.jobsTabs.active)
        #self.load_graph(self.jobsTabs.active)
        #print("change")
        1+1

    def find_models(self):
        #Check if prediction dir exist
        dirs = os.listdir(self.workdir)
        if not "predictions" in dirs:
            pn.state.notifications.error("No 'predictions' folder in workdir", 2000)
            return 0
        predictionFolder = self.workdir+"/predictions"
        self.jobs = [name for name in os.listdir(predictionFolder) if os.path.isdir(os.path.join(predictionFolder, name))]
        if len(self.jobs) == 0:
            from glob import glob
            a3mfile = glob(f"{predictionFolder}/*.a3m")[0]
            jobname = Path(a3mfile).stem
            self.jobs = [jobname]
            self.tabs_index[0] = jobname
            
        

    def graph_PAE_json(self,path):

        #1. Get PAE matrix
        f = open(path, "r")
        import json
        j = json.load(f)
        mat = np.asarray(j["pae"], dtype=np.float32)
        
        #2. Prepare graph object with plotly
        #2.a convert bwr color map from matplotlib. Function taken on internet, can't remember where..
        def matplotlib_to_plotly(cmap, pl_entries):
            h = 1.0/(pl_entries-1)
            pl_colorscale = []
            for k in range(pl_entries):
                C = list(map(np.uint8, np.array(cmap(k*h)[:3])*255))
                pl_colorscale.append([k*h, 'rgb'+str((C[0], C[1], C[2]))])

            return pl_colorscale
        
        bwr = matplotlib_to_plotly(matplotlib.cm.get_cmap('bwr'), 255)
        magma = matplotlib_to_plotly(matplotlib.cm.get_cmap('magma'), 255)

        heatmap = go.Heatmap(z=mat, colorscale=magma)
        fig = go.Figure(data=[heatmap])
        # mat = np.abs(30-mat)
        # fig = go.Figure(data = go.Surface(z=mat, 
        #                             colorscale=magma, 
        #                             )
        #         )
        # fig.update_layout(
        #           #title="PAE", 
        #           xaxis_title="Residue",
        #           yaxis_title="Residue", 
        #           legend_title="PAE",
        #         #   width=500,
        #         #   height=500,                  
        #     )
        return fig



    def add_graph(self, activetab):
        #activetab = self.jobsTabs.active
        selected_model = self.modelsMenus[activetab].value
        print(selected_model)
        jsonFile = selected_model.replace("_relaxed_","_unrelaxed_")+"_scores.json"
        

        job = self.tabs_index[activetab]
        if len(self.jobs) > 1:
            curdir = self.workdir+"/predictions/"+job
        else:
            curdir = self.workdir+"/predictions/"

        jsonFile = curdir+"/"+jsonFile
        fig = self.graph_PAE_json(jsonFile)
        return fig
        # self.PAEGraphsList[activetab] = fig

        
    def update_graph(self, event):
        activetab = self.jobsTabs.active
        job = self.tabs_index[activetab]
        if len(self.jobs) > 1:
            curdir = self.workdir+"/predictions/"+job
        else:
            curdir = self.workdir+"/predictions/"

        # print(self.jobsTabs)
        # Ok this is hard... Uncomment the print the hierarchy of the interface and find the ID of the element to change 
        # We have to do like this because otherwise no trigger are record and no change are shown.
        
        self.jobsTabs[activetab][1][0][0,0][1] = pn.pane.Plotly(self.add_graph(activetab))
        # print("---------")
        # print(self.jobsTabs[activetab][1][0][0,3])
        model_name = self.jobsTabs[activetab][1][0][0,0][0].value
        # self.jobsTabs[activetab][1][0][0,3:10] = self.load_pdbe(model=model_name, workdir=curdir)
        
        molstar_object = self.molstarLayout[activetab][0]#list(self.jobsTabs[activetab][1][0][0,3:10].objects.values())[0]
        
        self.test_update_molstar( 
            molstar_object,
            model = model_name,
            workdir=curdir
            )

        # self.PAEGraphsList[activatetab] = self.add_graph(activatetab)

    def test_update_molstar(self, molstar, model, workdir):    
        molstar.custom_data = {
                                    'url': f'assets/{workdir}/{model}.pdb',
                                    'format': 'pdb'
                                }
    
    def load_pdbe(self, model, workdir):
        local_pdbe = PDBeMolStar(
                                name='Local File',
                                sizing_mode='stretch_width',
                                height=500,
                                custom_data = {
                                    'url': f'assets/{workdir}/{model}.pdb',
                                    'format': 'pdb'
                                },
                                # alphafold_view=True, 
                            )
        self.molstarLayout.append(pn.Row(local_pdbe))
        return local_pdbe
        # self.molstar.custom_data = {
        #                             'url': f'assets/{workdir}/{model}.pdb',
        #                             'format': 'pdb'
        #                         }



    def create_visualisation_tabs(self, tabIndex):

        job = self.tabs_index[tabIndex]
        if len(self.jobs) > 1:
            curdir = self.workdir+"/predictions/"+job
        else:
            curdir = self.workdir+"/predictions"

        from glob import glob
        models = glob(f"{curdir}/*_relaxed_*.pdb")

        if len(models) == 0:
            models = glob(f"{curdir}/*_unrelaxed_*.pdb")
            hasRelax = False
        else:
            hasRelax = True
        
        #Just keep models name
        models = [Path(x).stem for x in models]
        
        self.modelsMenus.append(pn.widgets.Select(name="Model", options=models))
        self.modelsMenus[-1].param.watch(self.update_graph, "value")

        self.PAEGraphsList.append(pn.pane.Plotly(self.add_graph(tabIndex)))

        visuLayout = pn.GridSpec(sizing_mode='stretch_both', mode="override")

        colSettings =  pn.Column(self.modelsMenus[-1], 
                         self.PAEGraphsList[-1])

        visuLayout[:,0:3] = colSettings


        #Now the graph....
        self.molstar = self.load_pdbe(model=self.modelsMenus[-1].value, workdir=curdir)
        visuLayout[:,3:10] = self.molstarLayout[-1]
        return visuLayout
        


    def create_tabs(self):
        self.jobsTabs = pn.Tabs(dynamic=False)

        self.PNGS_layouts = [] #For now, all pngs will be loaded... Not optimal but I'm still wating an answer from https://discourse.holoviz.org/t/update-same-instance-of-widget-on-multiple-tabs/3699 
        for i,job in enumerate(self.jobs):
            self.tabs_index[i] = job #Set the "jobname" (baseame for files) for every tabs.
            self.PNGS_layouts.append(self.load_graph(i)) #Load graphcics
            visuPane = self.create_visualisation_tabs(i)
            self.jobsTabs.append((job, pn.Column(
                                                  pn.Card(self.PNGS_layouts[i], title="Main graphics",background="white"), 
                                                  pn.Card(visuPane, title="Visualisation", background="white"),
                                                 )
                                ))
            

    def load_graph(self, tabIndex):
        job = self.tabs_index[tabIndex]
        if len(self.jobs) > 1:
            curdir = self.workdir+"/predictions/"+job
        else:
            curdir = self.workdir+"/predictions"
        #For now it will first the graphs made by our beloved colabfold 

        # PNGS_layout = pn.Card(pn.pane.PNG(f"{curdir}/{job}_PAE.png",height=200,sizingmode="stretch_width"),
        #                         pn.Row(
        #                             pn.pane.PNG(f"{curdir}/{job}_coverage.png",sizingmode="stretch_width"),
        #                             pn.pane.PNG(f"{curdir}/{job}_plddt.png",sizingmode="stretch_width"),
        #                             ), width_policy="max",
        #                         )
        # allPAES = pn.pane.PNG(f"{curdir}/{job}_PAE.png")
        # coverage = pn.pane.PNG(f"{curdir}/{job}_coverage.png",sizingmode="stretch_width")
        # plddt = pn.pane.PNG(f"{curdir}/{job}_plddt.png",sizingmode="stretch_width")
        # PNGS_layout = pn.GridSpec(sizing_mode='stretch_both', max_height=600)
        
        PNGS_layout = pn.GridSpec(sizing_mode='stretch_both', max_height=600, mode="override")
        PNGS_layout[0,:] = f"{curdir}/{job}_PAE.png"
        PNGS_layout[1:3,:2] = f"{curdir}/{job}_coverage.png"
        PNGS_layout[1:3,2:4] = f"{curdir}/{job}_plddt.png"
        return PNGS_layout
        

        #self.jobsTabs[tabIndex][0][0] = self.PNGS_layout

        


class Ui():
    """
    Class for instancing the UI
    """
    def __init__(self):
        self.connnectivityCard = pn.Card(title = "Connectivity")

        self.AlphaFoldCar = pn.Card(title = "Alphafold Configuration")

        self.mainTabs = pn.Tabs(sizing_mode="stretch_both")

    def servable(self):
        self.mainUI.servable()



    
class Data():
    """
    Class that will handle all the datas
    """
    def __init__(self, ssh, alphafold):
        self.data = None

    
        

        

host = Host()
#ssh.init_connect()
host.init_panels()
#ssh.hostTab.servable()
gui = Ui()
alphafold = Alphafold(host)
results = Results(host)

#gui.connnectivityCard.append(ssh.hostTab)
#gui.AlphaFoldCar.append(alphafold.AlphaFoldTab)

#Add Settings
gui.mainTabs.append(("Settings",pn.Column(
        pn.Row(
            pn.Card(alphafold.msaTab,title="Sequence Search", collapsible=False),
            pn.Card(alphafold.modelTab, title="AlphaFoldModel", collapsible=False)
            ),
        # alphafold.GOGOGO,
        pn.WidgetBox(alphafold.editor),
        )
    )
)
#Add Terminal
gui.mainTabs.append(("Terminal",pn.Column(host.terminalLayout)))

#Add Results
gui.mainTabs.append(("Results",results.mainLayout))

# gui.servable()

mainGUI = pn.template.VanillaTemplate(title='AlphaFold @ I2BC', sidebar_width=400)
# mainGUI = pn.template.GoldenTemplate(title='Golden Template')
mainGUI.sidebar.append(pn.Column(
    pn.WidgetBox(host.hostTab),
    alphafold.GOGOGO,   
    )
)
mainGUI.main.append(gui.mainTabs)
gui.mainTabs.active=0

mainGUI.servable()

