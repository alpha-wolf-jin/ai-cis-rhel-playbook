


#source /ai/demojam/incident/.venv/bin/activate
#/ai/demojam/incident/aap/playbook/deepseek_generate_playbook.py 

source /ai/demojam/incident/.venv/bin/activate
/ai/demojam/incident/aap/playbook/deepseek_generate_playbook.py  \
--target-host "master-1"  \
--become-user "root"  \
--max-retries 6  \
--test-server "192.168.122.16"  \
--objective "Create an Ansible playbook that finds and kills processes that have packet_recvmsg in their stack trace." \
--requirement "Search for packet_recvmsg keyword in /proc/*/stack" \
--requirement "Extract the process ID from the path (e.g., from /proc/2290657/stack, extract 2290657)" \
--requirement "Kill the identified process(es) using kill -9" \
--requirement "Handle cases where: No matching processes are found, Multiple processes are found (kill all), Process disappears between detection and kill attempt" \
--requirement "Display useful information: Show what processes were found, Show the process details (ps output), Confirm successful termination"  \
--filename "kill_packet_recvmsg_process.yml"

./kcs_to_playbook.py --search "systemd failed" --target-host 192.168.122.17 --test-host 192.168.122.16 --filename verify_systemd.yml

python3 kcs_langgraph_playbook.py --search "ansible-builder failed" --max-retries 10 --test-host 192.168.122.16 --target-host 192.168.122.17


./cis_rhel8_rag_deepseek.py
Loading existing vector store from /home/jin/ai/rhel-cis/CIS_RHEL8_DATA_DEEPSEEK...
Vector store loaded with 1639 documents
Vector store ready
Type 'quit' or 'exit' to stop.

Enter checkpoint (or 'quit'): Manual mount command execution detected. This action may bypass persistent security configurations and result in violations of the CIS RHEL 9 Benchmark. Please list the affected checkpoints.


# Interactive mode - query checkpoints one by one
python3 cis_checkpoint_to_playbook.py

# Single checkpoint
python3 cis_checkpoint_to_playbook.py --checkpoint "1.1.1.1"

# With custom target host
python3 cis_checkpoint_to_playbook.py --checkpoint "1.1.1.1" --target-host 192.168.122.16

# Generate only (no execution)
python3 cis_checkpoint_to_playbook.py --checkpoint "5.2.4" --skip-execution

# Non-interactive (auto-accept requirements)
python3 cis_checkpoint_to_playbook.py --checkpoint "1.1.1.1" --no-interactive
