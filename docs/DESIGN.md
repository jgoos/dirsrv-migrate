Designing a Podman-based 389-DS Replication Testbed on macOS

This document describes a reliable, repeatable containerized environment for testing multi-node 389 Directory Server replication on macOS (using Podman). The design supports two distinct environments (DEV/INT) with different storage and lifecycle characteristics, two multi-master suppliers and multiple consumer replicas, or an all-supplier mesh topology, with end-to-end TLS, health checks, and comprehensive logging. We orchestrate container lifecycle with Podman Compose and configuration with Ansible roles/playbooks. Key decisions on networking, naming, and certificate handling are justified, and alternatives are discussed. A final section provides troubleshooting guidance for common issues.

## 0. Environment Matrix

We support two reproducible environments for 389-DS (containers on macOS Podman VM + RHEL VMs):
- **Development (DEV)** – persistent, longer-lived, restartable
- **Integration Testing (INT)** – ephemeral, no persistence, never restarted once seeded
- **VMs** – standard RHDS/389-ds-base on RHEL, must use same Ansible code

| Dimension | DEV (persistent) | INT (ephemeral) | VMs |
|-----------|----------------|-----------------|-----|
| Storage | Bind mounts (config/db/logs/certs) | Tmpfs/anon volumes (no bind mounts) | Local FS under /etc/dirsrv, /var/lib/dirsrv |
| Lifecycle | Start/stop/restart allowed | No restarts allowed; full teardown if needed | Start/stop/restart allowed (systemd) |
| Data seeding | Optional; incremental | Deterministic, clean every run | Deterministic |
| Image pinning | Tag-based (for iteration) | Immutable digest | Installed RPMs |
| Logging | Persist on host | Export artifacts before teardown | Local logs, copy summaries |
| DNS policy | Service names only | Service names only | FQDNs only |

1. Architecture & Topology

Topology Summary: We implement a flexible topology variable that can define either a 2-supplier multi-master + N consumers scenario or a full mesh of suppliers. In the default mode, two master servers (s1 and s2) replicate changes to each other (multi-supplier MMR) and to each consumer (e.g., c1, c2). Consumers are read-only replicas that do not propagate changes onward. The mesh variant treats all nodes as masters replicating with each other. Each directory instance has a unique replica ID and instance name, and all LDAP/LDAPS ports and certificate SANs are distinct. We prefer using upstream 389-DS container images (e.g. ghcr.io/389ds/dirsrv) for this lab to avoid RHDS licensing requirements, since 389-DS is the open-source core of RHDS and is suitable for testing (the upstream container uses a special entrypoint dscontainer to auto-create and run the server without systemd) ￼ ￼.

Topology Diagrams: The first diagram shows a 2-supplier with 2-consumer setup. Suppliers s1 and s2 replicate bidirectionally with each other (MMR), and each supplier pushes updates to each consumer (c1, c2). This dual-supplier feed to consumers provides redundancy (consumers will accept updates from either supplier). The second diagram shows a 4-node mesh where every node is a supplier replicating with all others (full multi-master mesh).

flowchart LR
    subgraph MMR Suppliers
      S1((Supplier s1))
      S2((Supplier s2))
    end
    subgraph Consumer Nodes
      C1((Consumer c1))
      C2((Consumer c2))
    end
    S1 <--> S2
    S1 --> C1
    S1 --> C2
    S2 --> C1
    S2 --> C2
    style S1 fill:#D5E8D4,stroke:#4C4;
    style S2 fill:#D5E8D4,stroke:#4C4;
    style C1 fill:#FFF2CC,stroke:#E0B000;
    style C2 fill:#FFF2CC,stroke:#E0B000;

flowchart TB
    A((Node 1)) <--> B((Node 2))
    A <--> C((Node 3))
    A <--> D((Node 4))
    B <--> C
    B <--> D
    C <--> D
    style A fill:#D5E8D4,stroke:#4C4;
    style B fill:#D5E8D4,stroke:#4C4;
    style C fill:#D5E8D4,stroke:#4C4;
    style D fill:#D5E8D4,stroke:#4C4;

Rationale: This design allows testing both hub-and-spoke replication (two masters as hubs, consumers as spokes) and fully meshed multi-master behavior. Each instance runs in its own container with a dedicated data store and log volume. We assign deterministic names (s1.dsnet.test, etc.) and replica IDs (e.g. 1001, 1002 for suppliers; 2001, 2002 for consumers) via the inventory. Deterministic naming ensures certificate Common Names and SANs match container hostnames to avoid TLS validation errors. All replication agreements use the containers’ DNS names (e.g. s1.dsnet.test:636) so that TLS certificates will be verified against those names. Using two masters covers conflict resolution and changelog management on multiple suppliers, while consumers allow testing one-way replication scenarios. The mesh configuration (e.g. 4 suppliers all replicating to each other) pushes the system to maximum connectivity and tests replication convergence and RUV (Replica Update Vector) consistency across all peers.

We opt for upstream 389-DS containers (from GitHub Container Registry or Docker Hub) rather than official RHDS images, because the upstream images are readily available and do not require a Red Hat subscription. The upstream container’s dscontainer entrypoint will initialize an instance on first startup and start the ns-slapd server process inside the container ￼. This avoids needing a full systemd inside the container (which the official RHDS UBI image might use) and fits better with rootless Podman usage. The upstream container supports configuration via environment variables (e.g., setting the Directory Manager password, suffix) and includes internal tuning for container environments ￼. (If RHDS images were used, one might need to run them with --privileged or an init system, which is more complex. So using 389-DS upstream is simpler for our testbed.)

## 1.5 Naming & Addressing

- **Containers**: always use Compose service names (ds-s1, ds-s2, …).
- **VMs**: always use FQDN (e.g., rhds-a1.example.com).
- **Variable**: `dirsrv_advertised_hostname_final = the only name ever used in agreements or LDAP URLs`.

**Resolution rule (priority order):**
1. `dirsrv_advertised_hostname` if defined
2. If `dirsrv_target_type == container` → `inventory_hostname` (service name)
3. Else → `ansible_fqdn` | default(`inventory_hostname`)

🚫 **No IP literals. No mixing service names and FQDNs.**

2. Podman Machine Setup (macOS host)

Podman VM Setup: Since containers cannot run natively on macOS, we create a Podman virtual machine using the podman machine command. The following initializes a VM with adequate resources and file sharing for our project:

podman machine init --cpus 4 --memory 8192 --disk-size 60 \
  -v ~/Projects/389ds-lab:/srv/389ds-lab --now

This creates a Podman VM with 4 vCPUs, 8 GB RAM, and a 60 GB disk. We also mount a host directory (~/Projects/389ds-lab) into the VM at /srv/389ds-lab for file sharing. By mounting our project directory (which will contain configs, certificates, and logs), those files will be accessible inside the VM and persist on the macOS host filesystem ￼ ￼. This is critical for log collection and for editing config files from macOS. (By default, Podman on macOS does not allow arbitrary volume mounts from the host unless they are set up via podman machine init -v ￼ ￼. We include this to avoid “No such file or directory” errors when binding host paths.)

We use rootless Podman (the default in Podman machine) to run containers for security and simplicity – the containers run under an unprivileged user in the VM. In rootless mode, containers do not get a global IP on the host’s network; instead networking is provided via a user-space NAT (slirp4netns or similar) ￼. This means each container does have an internal IP in a virtual network, but that IP is not directly visible on the macOS host. Rootless networking is sufficient for inter-container communication on the same user-defined network ￼, and it avoids needing root privileges in the VM. The drawback is that containers’ network traffic is a bit slower due to user-space NAT, and accessing container ports from macOS requires explicit port forwarding (we will address that shortly). Rootful Podman (running containers as root in the VM) could assign each container an IP on a bridged network and allow static IP assignment and possibly easier host access ￼, but it would complicate setup (requiring --rootful mode and potentially VM network interface tweaks). We choose rootless as it meets our needs and is the recommended default for Podman on Mac ￼. (If needed, one can switch the Podman machine to rootful via podman machine set --rootful, but then containers run as root in the VM ￼ ￼, and one must manage firewall and network differently. Our design sticks to rootless.)

Networking Configuration: All containers will be attached to a single user-defined Podman network named dsnet. This network provides an isolated IPv4 subnet for our containers and enables automatic DNS resolution of container names via Podman’s DNS plugin. We create the network in the Podman VM with a fixed subnet for predictability:

podman network create dsnet --subnet 10.89.0.0/24 --gateway 10.89.0.1 \
  --label dnsname=1 -d bridge

This defines a bridge network dsnet with subnet 10.89.0.0/24. The Podman DNS plugin (dnsname) is enabled (by default or via the label) so that containers on dsnet can resolve each other’s names ￼. Each container joining dsnet will receive an IP (e.g., 10.89.0.x) via host-local IPAM. We do not rely on static IP assignments for containers – while Podman does support --ip for static addresses even in rootless networks ￼, static IPs aren’t usually necessary because name resolution will be used for connectivity. (In rootless mode, container IPs are only reachable from within the VM’s network namespace, not directly from macOS ￼. So static IPs wouldn’t help macOS reach the containers without port forwarding. Instead, we use DNS names and, when needed, Podman’s port forwarding.)

Container DNS Names: We set the container hostnames to a stable fully-qualified domain (e.g. s1.dsnet.test). Internally, Podman’s DNS plugin (or Aardvark in newer Podman) will allow containers to resolve each other by hostname. By default, the plugin uses a DNS domain like dns.podman or none at all, so to ensure our custom *.dsnet.test names resolve, we leverage network aliases. In the compose file, each service on the dsnet network will get an alias equal to its FQDN (e.g., alias s1.dsnet.test). This causes the DNS service to recognize that name. We do not inject /etc/hosts entries; reliable DNS is a prerequisite and is enforced by preflight checks.

All containers are on a single network so that any container can talk to any other on the standard LDAP ports (389 for LDAP, 636 for LDAPS). We do not isolate containers from each other – in fact, we disable Podman’s network isolation option (we avoid --internal network, which would disable DNS plugin ￼). Within dsnet, there are no additional firewall rules blocking inter-container traffic, so replication (which uses LDAP/LDAPS) and normal LDAP queries can flow freely.

Host ↔ Container Connectivity: By default, in rootless Podman on macOS, containers are not directly addressable from the host by IP or hostname. All DNS resolution we set up (*.dsnet.test) works inside the Podman VM and containers, but macOS itself will not automatically know those names. If you need to run LDAP commands from macOS to a container (e.g., an ldapsearch from the host to s1.dsnet.test), there are two options:
	1.	Port Forwarding: We can publish container ports to the host. For example, publish s1’s LDAP port to macOS as 1389 and connect to localhost:1389. In Podman Compose, we avoid publishing by default (to keep containers isolated and to allow multiple instances of the lab without port conflicts), but we’ll demonstrate how to expose one master’s ports if needed for host-side testing.
	2.	macOS Resolvers: Optionally configure macOS to resolve *.dsnet.test via the Podman VM’s resolver (e.g., /etc/resolver). For ad‑hoc testing, prefer connecting to published localhost ports rather than editing /etc/hosts.

In summary, we choose rootless networking inside the Podman VM, meaning containers communicate through a user-space NAT network. This requires minimal configuration and is sufficient for our inter-container traffic. The implication is that container IPs are not visible externally ￼, but we mitigate that with DNS and optional port forwards. We also set the Podman network MTU to a safe value (Podman’s default is usually 1500 bytes, matching typical ethernet MTU). If running on VPNs or other environments where MTU issues occur, this could be tuned via --opt mtu=... on network creation. (For example, if using user-mode networking, an MTU of 1500 is fine; if using QEMU’s slirp, an MTU of 65520 might be seen, but fragmentation is handled. We haven’t needed a custom MTU in testing, but it’s mentioned as a tunable in Podman docs ￼.)

Finally, to avoid collisions across test runs, we ensure that container names and hostnames remain the same each run (Podman Compose will reuse the names or we explicitly set container_name). We also tear down the environment between runs (destroying containers and the dsnet network if needed) to avoid stale DNS cache entries or IP reuse issues. The podman network create with a fixed subnet ensures we get the same IP range each time, which helps with deterministic behavior. If multiple testbeds were run concurrently (e.g., two separate dsnet networks), the domain names could conflict; one could use different network/domain names per test to isolate them.

## 2.5 Storage Layout

**DEV**
- Persist all instance paths: /etc/dirsrv/..., /var/lib/dirsrv/..., /var/log/dirsrv/..., /etc/dirsrv/.../certs, /data/db.
- Bind mounts live under .ansible/containers/<svc>/....

**INT**
- Tmpfs/anon volumes only.
- Recommended tmpfs:
  - /var/lib/dirsrv/...: size=1G
  - /var/log/dirsrv/...: size=128M
- Any artifact needed must be copied out before teardown.

3. Podman Compose Configuration (4-node Example)

We use a Podman Compose YAML to define the directory server containers and their relationships. This Compose file can be run with the podman-compose tool (which uses the Podman socket behind the scenes). Below is a sample for 4 nodes (2 suppliers s1, s2 and 2 consumers c1, c2). It defines a user network, volumes for data/config/certs/logs, and health checks.

**DEV Environment**: All volumes and paths are set under the shared /srv/389ds-lab mount so they persist on the host.
**INT Environment**: Uses tmpfs/anonymous volumes only, with artifacts exported before teardown.

The compose configuration varies based on the environment:

# podman-compose.yml
version: '3.8'
services:
  s1:
    image: ghcr.io/389ds/dirsrv:latest
    container_name: s1               # Explicit container name to avoid random suffix
    hostname: s1.dsnet.test
    networks:
      dsnet:
        aliases: [ "s1.dsnet.test" ]
    environment:
      DS_DM_PASSWORD: "password"                     # Set Directory Manager password (env support in container)
      DS_SUFFIX_NAME: "dc=example,dc=com"             # Set suffix to auto-create on first startup
      # DS_BACKEND_NAME: "userRoot"                  # (Optional) backend name, default is 'userRoot'
    volumes:
      - /srv/389ds-lab/data/s1/config:/etc/dirsrv/slapd-s1:Z
      - /srv/389ds-lab/data/s1/data:/var/lib/dirsrv/slapd-s1:Z
      - /srv/389ds-lab/data/s1/certs:/etc/dirsrv/slapd-s1/certs:Z
      - /srv/389ds-lab/logs/s1:/var/log/dirsrv/slapd-s1:Z
      - /srv/389ds-lab/scripts/wait_for_dirsrv.sh:/usr/local/bin/wait_for_dirsrv.sh:ro
    healthcheck:
      test: ["CMD", "/usr/local/bin/wait_for_dirsrv.sh", "s1"]
      interval: 5s
      timeout: 3s
      retries: 50
    # ports:
    #   - "1389:389/tcp"
    #   - "1636:636/tcp"
    # If you need to access s1 from macOS, uncomment the above and add "127.0.0.1 s1.dsnet.test" in /etc/hosts.

  s2:
    image: ghcr.io/389ds/dirsrv:latest
    container_name: s2
    hostname: s2.dsnet.test
    networks:
      dsnet:
        aliases: [ "s2.dsnet.test" ]
    environment:
      DS_DM_PASSWORD: "password"
      DS_SUFFIX_NAME: "dc=example,dc=com"
    volumes:
      - /srv/389ds-lab/data/s2/config:/etc/dirsrv/slapd-s2:Z
      - /srv/389ds-lab/data/s2/data:/var/lib/dirsrv/slapd-s2:Z
      - /srv/389ds-lab/data/s2/certs:/etc/dirsrv/slapd-s2/certs:Z
      - /srv/389ds-lab/logs/s2:/var/log/dirsrv/slapd-s2:Z
      - /srv/389ds-lab/scripts/wait_for_dirsrv.sh:/usr/local/bin/wait_for_dirsrv.sh:ro
    healthcheck:
      test: ["CMD", "/usr/local/bin/wait_for_dirsrv.sh", "s2"]
      interval: 5s
      timeout: 3s
      retries: 50
    # Optionally publish ports for s2 similarly if needed.

  c1:
    image: ghcr.io/389ds/dirsrv:latest
    container_name: c1
    hostname: c1.dsnet.test
    networks:
      dsnet:
        aliases: [ "c1.dsnet.test" ]
    environment:
      DS_DM_PASSWORD: "password"
      DS_SUFFIX_NAME: "dc=example,dc=com"
    volumes:
      - /srv/389ds-lab/data/c1/config:/etc/dirsrv/slapd-c1:Z
      - /srv/389ds-lab/data/c1/data:/var/lib/dirsrv/slapd-c1:Z
      - /srv/389ds-lab/data/c1/certs:/etc/dirsrv/slapd-c1/certs:Z
      - /srv/389ds-lab/logs/c1:/var/log/dirsrv/slapd-c1:Z
      - /srv/389ds-lab/scripts/wait_for_dirsrv.sh:/usr/local/bin/wait_for_dirsrv.sh:ro
    healthcheck:
      test: ["CMD", "/usr/local/bin/wait_for_dirsrv.sh", "c1"]
      interval: 5s
      timeout: 3s
      retries: 50

  c2:
    image: ghcr.io/389ds/dirsrv:latest
    container_name: c2
    hostname: c2.dsnet.test
    networks:
      dsnet:
        aliases: [ "c2.dsnet.test" ]
    environment:
      DS_DM_PASSWORD: "password"
      DS_SUFFIX_NAME: "dc=example,dc=com"
    volumes:
      - /srv/389ds-lab/data/c2/config:/etc/dirsrv/slapd-c2:Z
      - /srv/389ds-lab/data/c2/data:/var/lib/dirsrv/slapd-c2:Z
      - /srv/389ds-lab/data/c2/certs:/etc/dirsrv/slapd-c2/certs:Z
      - /srv/389ds-lab/logs/c2:/var/log/dirsrv/slapd-c2:Z
      - /srv/389ds-lab/scripts/wait_for_dirsrv.sh:/usr/local/bin/wait_for_dirsrv.sh:ro
    healthcheck:
      test: ["CMD", "/usr/local/bin/wait_for_dirsrv.sh", "c2"]
      interval: 5s
      timeout: 3s
      retries: 50

networks:
  dsnet:
    name: dsnet      # Use the pre-created network
    external: true

Explanation: Each service corresponds to a directory server instance. The hostname field sets the container’s hostname to *.dsnet.test. We also apply a network alias matching that FQDN, ensuring that, within the dsnet network, the name is resolvable. The Compose file uses the external network dsnet that we created earlier (with DNS enabled). The volumes are mapped to host paths under /srv/389ds-lab (which is the mount point of our macOS project directory inside the VM). We separate each instance’s configuration, data, cert DB, and logs into distinct volumes:
	•	/etc/dirsrv/slapd-<name> (config files and certificate database directory)
	•	/var/lib/dirsrv/slapd-<name> (data files, DB records)
	•	/etc/dirsrv/slapd-<name>/certs (a sub-path for NSS DB, but we mount it explicitly for clarity – it could also reside under config)
	•	/var/log/dirsrv/slapd-<name> (log directory)

These will persist between container restarts. We use the :Z suffix on volume definitions, which is a Podman/SELinux option to relabel those volumes for container access (harmless on macOS, but included for completeness).

We set DS_DM_PASSWORD for each container so that the Directory Manager (admin user) password is known (“password” in this test). Without this, the upstream container would generate a random password or use a static insecure default, which is not ideal ￼. We also set DS_SUFFIX_NAME="dc=example,dc=com", instructing the entrypoint to initialize that suffix on first startup ￼. This saves us from having to run dsconf create-suffix manually; the container will create the suffix (and underlying backend) if provided. (The JeffersonLab extended image documentation confirms these env vars are supported: DS_DM_PASSWORD and DS_SUFFIX_NAME ￼. Official 389ds images have recently incorporated similar functionality, making initial setup easier.)

For health checks, we add a small script wait_for_dirsrv.sh (mounted into the container) and use Podman’s healthcheck feature. The script (provided later) will loop until it can confirm the directory server is running and listening on LDAPI/LDAP. We set a 5-second interval and up to 50 retries (which is 250 seconds max). The container will be marked “healthy” only after the script succeeds. This prevents our Ansible playbooks from configuring replication before the servers are ready. The depends_on ordering is not explicitly needed here because we will handle orchestration in Ansible after all are up, but health checks add safety.

Port Mapping: In this compose, we commented out an example of exposing ports for s1. By default, no ports are published, meaning the LDAP ports are only accessible within the Podman VM network. If you want to perform manual LDAP operations from macOS, you can publish e.g. 389 to 1389 and 636 to 1636 as shown (we choose non-privileged host ports since rootless Podman cannot bind below 1024 on the host without using the rootlessport helper). Then, on macOS, you could add an /etc/hosts entry pointing s1.dsnet.test to 127.0.0.1 and run ldapsearch -H ldap://s1.dsnet.test:1389 .... This is optional for interactive testing and is not needed for the automated Ansible workflow (Ansible will execute within the VM or via the Podman API).

Rootless Considerations: Because we are using rootless containers, Podman uses a slirp4netns or equivalent proxy for published ports. In testing, this works seamlessly – for example, running podman run -p 8080:80 ... on macOS will forward localhost:8080 to the container ￼. The same happens here with podman-compose when ports are specified. We note that in rootless mode, container DNS resolution requires the dnsname plugin (which we enabled). If you experience an issue where containers can’t resolve each other, ensure the dnsname plugin is installed/working (on some Podman installations it’s an extra package, but in Podman 4.x with netavark, name resolution is handled by Aardvark-dns out of the box). Also, ensure that only one network is attached; connecting a container to multiple user networks with DNS can confuse resolution ￼ (in our setup, each container is only on dsnet).

Container Entry/Startup: The image ghcr.io/389ds/dirsrv:latest will run the dscontainer entrypoint, which checks if an instance exists in /data (we’ve effectively mounted volumes to where it expects data and config) and creates one if not. Because we provided DS_SUFFIX_NAME, the entrypoint will also create the initial suffix (no entries yet, just the root entry for dc=example,dc=com) during first startup. It also disables some checks like strict hostname enforcement (since hostnames in containers can be dynamic) ￼. Each container thus will come up with a running directory server (slapd) with our desired suffix and ready for further configuration. The instance name inside container defaults to localhost in upstream images if not set; however, because we mount volumes named “slapd-s1”, the instance gets effectively named by that folder (and we can verify that within the container, the dirsrv instance is referred to as “slapd-s1” because our config volume path ends in that). We explicitly use consistent naming so that instance name = container name = volume names, to minimize confusion. (The instance name mostly matters for path naming and for logs, e.g. slapd-s1 appears in log file names and NSS DB path.)

4. Ansible Project Structure

We organize the automation in an Ansible project with inventory and roles to manage different stages: instance setup, TLS, replication, verification, and log collection. Below is a proposed structure of files:

├── inventories/
│   └── lab/
│       └── hosts.yml
├── group_vars/
│   └── all.yml
├── roles/
│   ├── dirs389.instance/
│   ├── dirsrv_tls/
│   ├── dirs389.replication/
│   ├── dirs389.verify/
│   └── dirs389.logs/
├── playbooks/
│   ├── provision.yml
│   ├── replicate.yml
│   ├── verify.yml
│   └── collect_logs.yml
└── Makefile

Inventory (hosts.yml): We define hosts corresponding to each container, using their FQDNs (which our environment can resolve inside the Podman VM or via Ansible connection). We group them into suppliers and consumers for convenience. Example:

# inventories/lab/hosts.yml
all:
  children:
    suppliers:
      hosts:
        s1.dsnet.test:
          ansible_host: s1.dsnet.test   # (If Ansible runs inside the Podman VM, it can use this name)
          replica_id: 1001
          ldap_port: 389
          ldaps_port: 636
          instance_name: "s1"
        s2.dsnet.test:
          ansible_host: s2.dsnet.test
          replica_id: 1002
          ldap_port: 389
          ldaps_port: 636
          instance_name: "s2"
    consumers:
      hosts:
        c1.dsnet.test:
          ansible_host: c1.dsnet.test
          replica_id: 2001
          ldap_port: 389
          ldaps_port: 636
          instance_name: "c1"
        c2.dsnet.test:
          ansible_host: c2.dsnet.test
          replica_id: 2002
          ldap_port: 389
          ldaps_port: 636
          instance_name: "c2"

Each host entry includes the planned nsds5ReplicaId for that server and its instance name (which corresponds to the container’s instance). If Ansible is run from the macOS host, ansible_host might need to be an address that is reachable (e.g., the Podman VM’s IP or localhost with port mapping); however, a simpler approach is to run Ansible inside the Podman VM (via podman machine ssh or using the VM as an inventory host itself) so that *.dsnet.test names resolve. Another approach is using the Podman connection plugin for Ansible (community.general.podman), which allows executing tasks inside containers by name – we could use that to target containers directly without SSH. For clarity, we assume Ansible is executed on the Podman VM (so it can reach containers by DNS name and default ports).

Group Variables (all.yml): Here we define global settings and defaults:

# group_vars/all.yml
suffix: "dc=example,dc=com"
topology: "mmr_2_suppliers_n_consumers"   # could be "mesh_all_suppliers" etc.
ca_dir: "/srv/389ds-lab/pki"              # path in VM for CA files
cert_profile: "server"                   # certificate profile name (just a label for our use)
replication_mgr_dn: "cn=Replication Manager,cn=config"
replication_mgr_pw: "Changeme!23"        # (Use Ansible Vault to encrypt in real usage)
enable_tls: true
log_capture: true
dm_password: "password"                  # Directory Manager password for all instances
env_type: "dev"                         # "dev" or "int" - controls lifecycle and storage behavior
dirsrv_no_restart: "{{ env_type == 'int' }}"  # Enforces no restarts in INT environment

Key variables explained:
	•	suffix: The DIT suffix we are testing replication on (all instances will have this suffix).
	•	topology: A flag to control which replication setup to apply. For example, if set to mesh_all_suppliers, the replication role might treat all hosts as suppliers and connect each to each. In mmr_2_suppliers_n_consumers, it will only make the two in the suppliers group mutual masters and others as consumers. The playbook/roles can use this to decide which agreements to create.
	•	ca_dir: Path where our certificate authority files will be stored (on the Podman VM or mounted path).
	•	replication_mgr_dn and _pw: The special replication user DN and password that will be created on each server for replication binds. We standardized on one credentials set for simplicity (all servers will have an entry cn=Replication Manager,cn=config with this password). This user will be used by suppliers to bind to peers. (You could have distinct ones per agreement, but one global user is easiest to manage.)
	•	enable_tls: A toggle to allow turning off TLS for troubleshooting or testing (if false, we could configure replication agreements over LDAP on port 389 without StartTLS, and skip certificate generation).
	•	log_capture: If true, our roles will attempt to gather logs after tests.
	•	dm_password: The Directory Manager password set in all containers (we used "password"). This is needed for Ansible to run dsconf or LDAP operations with admin rights.
	•	env_type: Controls environment behavior ("dev" for persistent/restartable, "int" for ephemeral/no-restarts).
	•	dirsrv_no_restart: Boolean flag that enforces lifecycle contracts (true for INT, false for DEV/VMs).

Roles: We break out roles for clarity:
	•	dirs389.instance: Tasks to ensure the DS instances are up and configured with basic settings (creating suffix if not already present, setting schema or id2entry settings if needed, ensuring Directory Manager password is set – though in our case it’s done via env).
	•	dirsrv_tls: Tasks to set up the Certificate Authority and issue server certificates, and configure each DS instance to trust the CA and use its server cert for LDAPS.
	•	dirs389.replication: Tasks to configure replication: enable the replication plugin on each instance (with the correct role and replica ID) and set up replication agreements between the appropriate pairs. This role will use the topology variable to decide which agreements to create.
	•	dirs389.verify: Tasks to verify that replication is working (e.g., check that each supplier and consumer has the expected RUV, possibly create a test entry on one supplier and see if it appears on others).
	•	dirs389.logs: (Optional) Tasks to adjust log settings on each instance (like setting log level or rotation policy) and to collect logs.

Playbooks: We foresee separate playbooks for different phases:
	•	provision.yml: Bring up the containers (maybe call out to Podman Compose via ansible.builtin.command) and run the instance and tls roles to initialize everything. For example, this playbook might have a block that waits for the container health checks (or explicitly uses our wait script) then includes dirsrv_tls.
	•	replicate.yml: Run the dirs389.replication role to create replication agreements and initialize replicas.
	•	verify.yml: Run dirs389.verify to perform post-setup checks (and possibly run any test cases or assertions).
	•	collect_logs.yml: Run dirs389.logs or otherwise gather logs into an artifact.

The Makefile (discussed later) will tie these together.

Notes on Ansible execution: Since Podman doesn’t run an SSH service in containers by default, if we want to use ansible_connection: podman or Docker connection, we could. Another approach is to SSH into the Podman VM and treat each container as reachable by its DNS name and LDAP ports. There’s even the possibility to use Ansible’s URI module or an LDAP module to perform operations via LDAP (binding to each server’s LDAP interface on 389/636). For example, adding entries or checking health could be done with ldapsearch commands executed via Ansible’s shell on the VM. For the replication setup, however, using the dsconf CLI on the VM (targeting each instance) is straightforward. We’ll assume the Ansible control node has the 389-DS client tools installed (dsconf, dsctl, ldapmodify, etc.), which we can arrange by installing 389-ds-base package on the Podman VM or using a helper container. Alternatively, we can podman exec into a container to run dsconf there. There are many options; to keep it simple, tasks will likely do something like:

- name: Enable replication plugin on supplier
  shell: |
    dsconf -D "cn=Directory Manager" -w "{{ dm_password }}" ldap://{{ inventory_hostname }}:{{ item.ldap_port }} \
      replication enable --suffix "{{ suffix }}" --role "{{ item.role }}" {% if item.role == 'supplier' %} --replica-id {{ item.replica_id }} --bind-dn "{{ replication_mgr_dn }}" --bind-passwd "{{ replication_mgr_pw }}" {% endif %}
  delegate_to: localhost
  with_items:
    - { inventory_hostname: "s1.dsnet.test", ldap_port: 389, role: "supplier", replica_id: 1001 }
    - { inventory_hostname: "s2.dsnet.test", ldap_port: 389, role: "supplier", replica_id: 1002 }
    - { inventory_hostname: "c1.dsnet.test", ldap_port: 389, role: "consumer" }
    - { inventory_hostname: "c2.dsnet.test", ldap_port: 389, role: "consumer" }

The above pseudo-task shows how we might loop through and enable replication on each. (In practice, we would gather the hosts from inventory groups rather than hardcoding, but this illustrates the idea.)

5. Certificate Authority & Automation

We enforce TLS everywhere for LDAP communication (both client queries and replication traffic). To do this in a test environment, we run our own local Certificate Authority and issue server certificates for each DS instance. The steps include:
	1.	Generate a CA key and self-signed certificate (e.g., using OpenSSL).
	2.	For each server (s1, s2, c1, c2), generate a private key and CSR (Certificate Signing Request) with the CN set to the server’s name (e.g., s1.dsnet.test) and a DNS Subject Alternative Name of the same. Then sign it with the CA to produce a server certificate.
	3.	Import the CA certificate into each server’s NSS certificate database as a trusted CA.
	4.	Import each server’s key and certificate into that server’s NSS DB, and configure the server to use it.

We can automate these with an Ansible role or script. For example, using the openssl command-line:
	•	Create CA key: openssl genpkey -algorithm RSA -out ca.key -pkeyopt rsa_keygen_bits:2048
	•	Create CA cert: openssl req -x509 -new -nodes -key ca.key -subj "/CN=389DS Test CA" -days 365 -out ca.crt
	•	For each host:
	•	Generate key: openssl genpkey -algorithm RSA -out {{ host }}.key -pkeyopt rsa_keygen_bits:2048
	•	CSR: openssl req -new -key {{ host }}.key -subj "/CN={{ host }}.dsnet.test" -reqexts SAN -config <(printf "[req]\ndistinguished_name=dn\n[san]\nsubjectAltName=DNS:{{ host }}.dsnet.test") -out {{ host }}.csr
	•	Sign: openssl x509 -req -in {{ host }}.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 365 -extensions san -extfile <(printf "subjectAltName=DNS:{{ host }}.dsnet.test") -out {{ host }}.crt
(Alternatively, one could use an OpenSSL config file for SAN. The key point is each cert’s SAN matches the container DNS name.)

Ansible can simplify some of this (with the openssl_certificate module for example). Once we have s1.crt and s1.key etc., we need to get them into the container’s NSS database. 389 DS uses an NSS DB (cert8 or cert9 DB in SQL format, located in /etc/dirsrv/slapd-INSTANCE/). The upstream container likely already initialized a database there (with a self-signed cert if we let it, but since we provided no TLS on startup, it might not have any cert yet). We will do the following on each container:
	•	Copy the CA cert (ca.crt) to the container (or mount it via the shared folder).
	•	Use certutil to add the CA cert as trusted:

certutil -A -d sql:/etc/dirsrv/slapd-INSTANCE/certs \
  -n "LocalTestCA" -t "CT,C,C" -a -i /etc/dirsrv/slapd-INSTANCE/certs/ca.crt

This command (run inside container or via podman exec) adds a Certificate Authority labeled “LocalTestCA” and marks it trusted for client and server auth ￼ (trust flags “CT,C,C” mean trusted CA for SSL client, SSL server, and email).

	•	Combine the server key and cert into a PKCS#12 file (since pk12util is often easiest to import both together). We can do on the host: openssl pkcs12 -export -inkey s1.key -in s1.crt -certfile ca.crt -passout pass:Secret123 -out s1.p12. Then copy s1.p12 to container.
	•	Import PKCS#12 into NSS DB:

pk12util -i /etc/dirsrv/slapd-INSTANCE/certs/s1.p12 -d sql:/etc/dirsrv/slapd-INSTANCE/certs -W Secret123

This will prompt (or use -W to supply the import password) and import the cert and key. After this, certutil -L -d sql:/etc/dirsrv/slapd-INSTANCE/certs should list a cert (probably named after the “Friendly Name” which by default might be “1” or “Server-Cert”).

	•	Rename or ensure the certificate has a known nickname. We can specify -n "Server-Cert" in the pk12util import by first adding an alias in the PKCS#12 or by using certutil -M to modify trust. Simpler: when generating the CSR, use CN identical to what we want the nickname to be – in 389 DS, by default the nickname is the CN. We used CN=s1.dsnet.test, so likely the cert nickname becomes s1.dsnet.test. We can use that.
	•	Set the nsSSLPersonalitySSL attribute in cn=encryption,cn=config to the nickname of the server cert. For example:

dsconf -D "cn=Directory Manager" -w password ldap://s1.dsnet.test security tls enable --nss-cert-name "s1.dsnet.test"

If dsconf security tls enable is available, it might set nsslapd-securePort: 636 and the cert name accordingly ￼. Otherwise, we can do:

dsconf -D "cn=Directory Manager" ldap://s1.dsnet.test config replace nsslapd-securePort=636
dsconf -D "cn=Directory Manager" ldap://s1.dsnet.test config replace nsSSLPersonalitySSL="s1.dsnet.test"
dsconf -D "cn=Directory Manager" ldap://s1.dsnet.test config replace nsSSLClientAuth=allowed

The above ensures LDAPS is enabled on port 636 and the server will use the cert we imported. nsSSLClientAuth=allowed means client certificates are not required (default). We then restart the instance (or use dsctl restart) for changes to take effect.

All these steps will be encapsulated in the dirsrv_tls Ansible role. After this, each server will accept LDAPS connections on 636 with our issued cert, and each server will trust the CA – so they will trust each other’s certs as well, since all were issued by the same CA. This is critical for replication: if s1 connects to s2 over LDAPS, s1 (acting as an LDAP client) needs to trust s2’s cert. By importing the CA on every server’s NSS DB (which is used for both server and client operations in 389DS), we satisfy that. This approach avoids the pitfalls of self-signed certs per host (which would require either disabling cert verification or manually trusting each other’s certs) ￼ ￼. Using a single CA is the recommended way in multi-server setups to ensure mutual trust.

We will provide a script or role to generate the CA and server certs. For simplicity, we might generate them on the macOS host or Podman VM and then use ansible.builtin.copy or the shared volume to distribute them to containers. The certificate role also will likely call certutil and pk12util via Ansible’s command module (executing inside the container – possibly using the Podman connection or via podman exec). Since these tools might not be in PATH of the running container by default, we may have to install the nss-tools package inside the container or rely on dsconf security certificate add. Notably, 389 DS now has a command to add certificates from files:

dsconf -D "cn=Directory Manager" ldap://s1.dsnet.test security certificate add --file /etc/dirsrv/slapd-s1/certs/s1.crt --name "s1.dsnet.test"
dsconf -D "cn=Directory Manager" ldap://s1.dsnet.test security certificate set-trust-flags --flags "CT,C,C" "s1.dsnet.test"

But the above only adds the certificate, not the key – so it’s used if the key is already in NSS (which it isn’t). So we stick to the NSS tools method. (The Server Fault Q&A confirms the approach of importing an external cert to fix LDAPS issues ￼.)

After TLS setup, verification: We will test that an LDAPS connection works on each. E.g., ldapsearch -H ldaps://s1.dsnet.test -x -D "cn=Directory Manager" -w password -b "" -s base objectClass=* should return the Root DSE. Also, for replication, we will configure agreements to use ldaps://...:636 and the servers will authenticate using the replication manager DN over that secure channel.

In summary, the certificate automation provides:
	•	A local CA (ca.crt and ca.key) that we trust implicitly for tests.
	•	Per-node certificates with SAN matching their *.dsnet.test name.
	•	Automated import into each instance’s NSS DB using certutil and pk12util (driven by Ansible tasks).
	•	Configuration of 389-DS to enable LDAPS using those certs.

We will also ensure the clients (if any, e.g., if running ldapsearch from the Podman VM or macOS) trust the CA. If doing manual tests on macOS with ldapsearch, we can either supply -CAfile ca.crt or add the CA to macOS keychain for convenience. Within the Podman VM, adding the CA to /etc/pki/ca-trust (if Fedora CoreOS, might have different mechanism) could be done so that e.g. openssl s_client and such recognize it. This is optional; our focus is server-to-server trust.

6. Service Readiness & Health Checks

Readiness Problem: After starting containers, the directory server processes inside need some time to become ready (listen on LDAPI/LDAP sockets, finish initialization). We must avoid race conditions where Ansible attempts replication setup on a server that isn’t accepting connections yet. To handle this, we implement both active health checks in Podman and an Ansible wait strategy.

We provide a script wait_for_dirsrv.sh (as seen mounted in compose). This script takes an instance name argument and performs checks:

#!/bin/sh
INST="$1"
SOCK="/var/run/slapd-${INST}.socket"
for i in $(seq 1 50); do
  # Check if LDAPI socket exists
  if [ -S "$SOCK" ]; then
      # Optionally, use dsctl to check status
      dsctl $INST status 2>&1 | grep -q "running"
      STATUS=$?
      if [ $STATUS -eq 0 ]; then
          exit 0   # success, server is running
      fi
  fi
  sleep 2
done
echo "Directory server $INST not ready after 100s" >&2
exit 1

This script first looks for the LDAPI Unix domain socket (/var/run/slapd-s1.socket for instance s1). The presence of the socket indicates the process has at least started listening on LDAPI. Then it runs dsctl <inst> status. dsctl status returns 0 if the instance is running, and prints status info. By grepping for “running” we ensure the server is fully up. The script loops up to 50 times (sleeping 2s each loop, i.e., ~100 seconds max). Podman will run this as the container healthcheck command. If it exits 0, the container is marked healthy. If the loop expires, it exits 1 and healthcheck will report unhealthy.

We also have the option to check the LDAP port (389) directly. Alternatively, using dsconf or ldapsearch in the script could work: e.g.,

ldapsearch -x -H ldapi://%2fvar%2frun%2fslapd-${INST}.socket -s base -b "" objectClass=* && exit 0

which would succeed if the server responds. However, calling ldapsearch for 50 retries is a bit heavier than dsctl status. The dsctl approach is fine and does not require credentials.

In our Ansible flow, we will still ensure not to proceed until all servers report healthy. We can use the Podman healthcheck status via podman ps -a --format "{{.Names}} {{.Healthcheck.Status}}" or simply rely on the script logic by invoking it from Ansible. For example, an Ansible task:

- name: Wait for all Directory Servers to be ready
  shell: podman exec {{ item }} /usr/local/bin/wait_for_dirsrv.sh {{ inventory_vars[item]['instance_name'] }}
  with_items:
    - s1
    - s2
    - c1
    - c2

(This assumes Ansible is running on the VM and has access to the Podman CLI; it will exec into each container and run the same script, ensuring readiness before moving on.)

Once this passes, we know that:
	•	The LDAPI socket is available (so local operations like dsconf with LDAPI SASL could be used if we wanted).
	•	The server is listening on TCP 389/636 (implicitly, if status is running).
	•	The Directory Manager account is created (that happens at instance init).
	•	Our suffix exists (since we gave DS_SUFFIX_NAME).

Health Endpoint Alternatives: If we needed an HTTP-based healthcheck (for e.g., some orchestrators), we might expose the 389-DS HTTP admin interface (if configured) or use a script as done. Our approach is sufficient.

Avoiding Pitfalls: A known issue in container starts is that sometimes the server may start but the suffix/backends may not be fully available for a moment (especially if import tasks or heavy recovery are happening). Our wait script using dsctl status should handle most cases. If more granularity is needed, we could try dsconf <inst> backend status or attempt an actual LDAP operation on the suffix. But for now, a basic readiness check is fine.

We also set up the containers with healthcheck retries=50 in compose, meaning Podman will not mark unhealthy until many failures (5s * 50 = 250s). This ensures a slow-starting server (perhaps if it was restoring a DB) isn’t falsely marked unhealthy too soon.

Ansible module consideration: If we wanted, we could write a small Ansible module or use the community.general.wait_for to check the LDAP port. For instance:

- name: Wait for LDAP port on s1
  wait_for:
    host: s1.dsnet.test
    port: 389
    state: started
    timeout: 120

However, this only checks socket open, not that the server is fully initialized to respond to operations. It’s a weaker check (the socket might open before suffix is ready). So our approach using dsctl is more tied to the application’s actual readiness.

In summary, our readiness strategy is:
	•	Built-in Podman healthchecks (visible via podman ps) with a robust script.
	•	Ansible waiting on those healthchecks (or reusing the script) before proceeding to config changes.

7. Replication Configuration Automation

With servers up and TLS in place, we automate setting up replication. Key steps:
	•	Enable replication on each instance’s suffix with the appropriate role (supplier or consumer) and unique replica ID.
	•	Create a Replication Manager entry on each instance (especially consumers) so that suppliers can bind to it.
	•	Set up replication agreements between the instances according to our topology variable.
	•	Initialize consumer databases from a supplier (a one-time total update).
	•	Verify that replication is working (check status and RUV).

Enabling replication & Replica IDs: 389 DS requires that each replica participating in replication be assigned an nsds5ReplicaId (1–65534) for each suffix. This is done by enabling the suffix for replication on that server. Using dsconf:

dsconf -D "cn=Directory Manager" -w password ldap://s1.dsnet.test replication enable \
    --suffix="dc=example,dc=com" --role="supplier" --replica-id=1001 \
    --bind-dn="cn=Replication Manager,cn=config" --bind-passwd="Changeme!23"

This single command, if successful, does a few things on s1:
	•	It creates the entry cn=Replication Manager,cn=config with the given password (since we provided –bind-DN and –bind-passwd) ￼ ￼. This user will be allowed to perform replication operations.
	•	It sets the server’s role to supplier for that suffix and assigns it replica ID 1001 ￼ ￼.
	•	It likely enables the changelog plug-in automatically. (The changelog is required on suppliers to track changes. Historically one had to manually ensure cn=changelog5,cn=config was present; dsconf replication enable should handle it by creating cn=changelog if needed and setting up default settings.)

For s2, we do the same with --role supplier --replica-id 1002. For consumers c1 and c2, we run:

dsconf -D "cn=Directory Manager" -w password ldap://c1.dsnet.test replication enable \
    --suffix="dc=example,dc=com" --role="consumer"

For a consumer, no replica ID is needed (they don’t generate changes). We might still specify --bind-DN and password to create a replication manager on the consumer, but the docs indicate --bind-passwd is only used for suppliers (it says This will create the manager entry if a value is set ￼). On a consumer, specifying it is probably ignored (since consumers don’t have a changelog or accept updates from others? Actually, in 389, a consumer still needs to accept incoming updates – it’s the supplier side that initiates, but the consumer allows the bind. The consumer can allow the supplier to bind as any user with replication rights; by default the supplier could use the consumer’s Directory Manager. But we prefer to have created a replication user on consumer for the bind). So to be safe, we can create the replication manager on each consumer manually:

dsconf -D "cn=Directory Manager" -w password ldap://c1.dsnet.test replication create-manager \
    --name "Replication Manager" --passwd "Changeme!23"

This would add cn=Replication Manager,cn=config on c1 with the given password ￼ ￼. (If the enable command didn’t already do it on a consumer, this ensures it.)

We ensure each server now has a replication manager entry with the same DN and password. For security in production, each supplier-consumer pair could use unique credentials, but one account is easier for lab.

Creating Agreements: Now the heart of replication: setting who replicates to whom. We use dsconf repl-agmt create on the supplier side to create agreements. For example, to have s1 push to c1, run on s1:

dsconf -D "cn=Directory Manager" -w password ldap://s1.dsnet.test repl-agmt create \
    --suffix="dc=example,dc=com" --host="c1.dsnet.test" --port=636 \
    --conn-protocol=LDAPS --bind-dn="cn=Replication Manager,cn=config" \
    --bind-passwd="Changeme!23" --bind-method=SIMPLE --init "s1-to-c1"

This defines an agreement named “s1-to-c1” on s1 for suffix “dc=example,dc=com”. It will connect to host c1.dsnet.test port 636 using LDAPS, binding as the replication manager DN with the known password, and using simple auth ￼ ￼. The --init flag tells it to perform an initial push of all data after creation ￼ ￼. We will do similar:
	•	s1-to-c2 (s1 -> c2)
	•	s2-to-c1 (s2 -> c1)
	•	s2-to-c2 (s2 -> c2)
This covers suppliers to consumers. For the two suppliers themselves (MMR link):
	•	On s1: create s1-to-s2: pointing to s2 on port 636, using replication manager bind.
	•	On s2: create s2-to-s1: pointing to s1.

Thus each supplier has an outbound agreement to the other supplier, making a full mesh between them (which is required for multi-master; 389 DS doesn’t automatically mirror an inbound agreement). After these six agreements are created (for 2 suppliers, 2 consumers scenario), the topology is set. The --init flag we include on consumer agreements ensures the consumers get populated. For the supplier-supplier agreements, we have to be careful: if both suppliers start empty, we don’t necessarily need to init (no data to push). If one had data that the other didn’t, we’d init that direction. In our case, since all servers were created empty (no entries in the suffix yet), it’s fine to create agreements without init for masters. Alternatively, we could add a test entry on s1 before setting up, then use --init on s1->s2 to push it. But that might be overkill. We can just not specify --init for s1<->s2, which means they’ll start replicating new changes (if any).

RUV and initialization sanity: After setting agreements, we likely want to initialize each consumer. We used --init which triggers total update immediately. That should copy all entries from supplier to consumer. If the suffix was empty, it just sets up an initial RUV. If we had added some base entries (like a test user), that would copy over. We should monitor the progress – nsds5replicationLastInitStatus attribute on the agreement entry can be checked. Our verify playbook can poll until nsds5replicaLastInitEnd is non-zero on consumers. But since our data is minimal, it should be quick.

Idempotency: Running the replication setup role again should not duplicate agreements. If we try to create an agreement with an existing name, dsconf will error. We can avoid issues by choosing a consistent naming scheme and checking for existing agreements. dsconf replication list can list suffixes replicated and maybe show agreements. Alternatively, we can use ldapsearch to find if an agreement entry of that name exists under cn=replica,cn="dc=example,dc=com",cn=mapping tree,cn=config. However, for our lab, it might be acceptable to run the playbook once per environment startup (and use reset playbooks to tear down if needed). We will note in docs that re-running should either skip or you must remove agreements first (perhaps our reset_hard target will do that by wiping config volumes).

Replication Attributes per node: The playbook will set nsds5ReplicaId via the dsconf replication enable as above. This actually writes an entry cn=replica,cn="dc=example,dc=com",cn=mapping tree,cn=config with attributes including nsds5ReplicaId: 1001 (on s1 for example) and references to the replication manager DN (it will set nsds5ReplicaBindDN: cn=Replication Manager,cn=config). On a consumer, the replica entry exists too but with no changelog and possibly a different role flag.

We will ensure each instance uses its inventory-provided replica_id to avoid duplicates – duplicates would confuse replication (two servers with same RID would be considered the same source). The chosen numbers (1001,1002,2001,2002) are arbitrary but unique across all. They are also >1000, which is not necessary but fine.

Access Control: 389 DS by default allows the replication manager full access to do replication updates. The enable command likely sets up necessary ACIs. If not, we might have to add ACIs to allow “cn=Replication Manager,cn=config” to write the suffix. Typically, the replication manager DN is added to a special entry in the replica config (nsds5replicabinddn etc.) and that might implicitly trust it. We’ll rely on defaults.

Verification of replication: The dirs389.verify role will perform checks such as:
	•	On each server, run dsconf replication status --suffix dc=example,dc=com ￼. This command shows the status of all agreements for that server (e.g., a supplier will show whether each consumer agreement is online and when last update was). We can parse that for errors.
	•	Run dsconf replication get-ruv --suffix dc=example,dc=com on each server ￼. The RUV (Replica Update Vector) contains each supplier’s RID and the max CSN from them that this server has seen. We expect that after initialization and a little time, each server’s RUV lists all supplier IDs. For example, on s1’s RUV, we should see id 1001 and 1002 with some CSN timestamps. On c1’s RUV (since it’s read-only, it might not have its own id in RUV or it might, but anyway it should have 1001 and 1002).
	•	Optionally, do a functional test: add an entry on s1 via ldapadd, wait a moment, and search on c2 to see if it arrived. Similarly, modify or delete to test replication of changes.
	•	Check that no errors are present in errors log regarding replication (like “connection error” or “bind failed”).

Replica Initialization Order: One nuance: when setting up two new suppliers, sometimes one should be initialized from the other to sync any existing data. We started both empty, so it’s fine. If we wanted, we could designate s1 as the config supplier and initialize s2 from s1 as well. Given emptiness, not needed. But our tasks might still perform an initialize: e.g., we could do:

dsconf -D "cn=Directory Manager" -w password ldap://s2 replication initialize --from-host s1.dsnet.test --from-port 636 --bind-method SIMPLE --bind-dn "cn=Directory Manager" --bind-passwd password --suffix dc=example,dc=com

This forces a full copy from s1 to s2. We might skip this since after creating symmetric agreements, any new data we add will replicate anyway. If we add initial data, we could use one-time init to ensure they match. We’ll note this as an option.

Teardown of replication: If we run make reset_hard, we might nuke volumes, which removes replication config anyway. If we wanted a softer teardown (e.g. remove all agreements and reset the replication config to non-replicated), we could:
	•	dsconf replication disable --suffix ... on all (that removes replica entries and changelogs).
	•	Remove cn=Replication Manager,cn=config entries if desired.
But in practice, wiping the data and starting fresh is easier for test cycles (given our automation can recreate everything quickly).

Changelog tuning: The changelog (stored in cn=changelog under the instance, by default in slapd-INSTANCE/changelogdb directory) can grow. By default it keeps entries until consumed by all replicas. Since we only have a few replicas and presumably not huge loads, default is fine. We could set nsslapd-changelogmaxage (to age out older than e.g. 7 days) in config if needed. We won’t complicate now.

8. Logging & Observability

Logging is critical for diagnosing replication issues and verifying behaviors. We take a two-pronged approach: persistent DS log files on volumes, and container stdout logs captured via Podman.

Directory Server Logs: Each 389-DS instance produces at least three logs by default:
	•	Error log (errors): internal errors, startup messages, replication errors, etc.
	•	Access log (access): every LDAP operation processed.
	•	Audit log (audit): changes in LDIF format (if enabled).
There is also an audit failure log and security log (for authentication events) if enabled. By default, the error log is on, access log is on, audit is off (depending on config). We ensure these logs are directed to /var/log/dirsrv/slapd-<inst>. In our compose, we mounted that directory. Thus, logs persist even if the container is removed, and multiple runs append to the existing logs (unless we remove the volume or configure rotation).

We will configure log rotation to prevent unlimited growth. 389 DS can rotate logs by size and/or time, and limit the number of old files to keep ￼ ￼. The default for error log is to rotate weekly and keep only 1 file (meaning it essentially overwrites each week) ￼ ￼. For access log, default keep is 10 files, 100MB each max, rotate weekly ￼ ￼. We likely want more retention on error logs for our testing. We can set in cn=config:

nsslapd-errorlog-maxlogsperdir: 10
nsslapd-errorlog-logrotationtime: 1
nsslapd-errorlog-logrotationtimeunit: day

This would rotate the error log daily and keep 10 days of logs ￼ ￼. Similarly for access:

nsslapd-accesslog-maxlogsperdir: 5
nsslapd-accesslog-maxlogsize: 50

(for example, keep 5 files of 50MB each). We can do this via dsconf config replace as shown in Red Hat docs ￼ ￼. Our Ansible dirs389.logs role can apply these settings idempotently. With this, logs will rotate into numbered files (e.g., access, access.20250906 etc., depending on format). We also ensure the logs are timestamped in human-readable form (389 DS by default uses high-resolution timestamps; we might leave that or disable high-res if it’s too fine).

Container Logs (stdout/stderr): Podman captures the output of the container’s process. In our case, the ns-slapd process is launched by the entrypoint. It may output some startup info to stdout/stderr (e.g., “Server started”). It might not log much after that (since most logs go to files). However, if a severe error occurs (like assertion failure or crash), it might print to stderr. We still capture these logs because they can indicate if the container entrypoint had issues.

We use podman logs to fetch these. For example:

podman logs -t s1 > container-s1.log

The -t includes timestamps ￼. We do this for each container at the end of the test run. We could also use podman pod logs if they were in one pod, but we have them separate. The container logs will contain the healthcheck script’s output too (if any failures occurred, our script echoes a message which would appear as well).

Metrics/Monitoring: While not asked explicitly, we note that 389 DS provides SNMP and other monitoring. We won’t enable those now, but one can use dsconf monitor or check cn=monitor in LDAP to gather stats (Ansible could query that to measure replication delays etc. – out of scope for now).

Time Synchronization: It’s important that all containers’ clocks are in sync for replication (CSNs include timestamps). Our containers inherit time from the Podman VM (which likely syncs with host or has an NTP). We should ensure the Podman VM’s time is correct (Podman machine typically keeps in sync with host; if not, enabling chronyd in FCOS or VM is needed). We will mention to ensure host time is correct to avoid replication anomalies (if one server’s clock is far ahead, its changes might be seen as “future” on others). For tests on one machine, usually not an issue.

Collecting Artifacts: We create a target (via playbook or Makefile) to gather all logs into one archive:
	•	Directory logs: from volumes in /srv/389ds-lab/logs/*. Since that path is on the Mac host (through the mount), we could zip them directly on macOS. But to keep environment-contained, we might zip on VM then copy out. Simpler: just have Ansible on Mac run a local task to zip the shared folder’s logs.
	•	Container logs: our Ansible role will run podman logs -t <name> and capture the output. It can store them as files under, say, .ansible/artifacts/ directory.
	•	We then zip the logs and container logs together, naming the zip with a timestamp or test ID. For example, .ansible/artifacts/2025-09-06_10-45-00_logs.zip.

The Makefile target logs will call ansible-playbook collect_logs.yml, which will do the above and then perhaps do ansible.builtin.fetch if needed to bring the zip to a known location on Mac. However, because of volume mount, the logs are already on Mac, and we could just instruct the user to check logs/ directory. But the single zip is convenient for archival. We’ll implement it for completeness.

Log Contents: The error logs will reveal things like bind failures (e.g., if certificate trust fails, you’d see an error when replication tries LDAPS: “SSL alert handshake failure” or similar). Access logs will allow verifying that replication binds happened (you’d see a BIND operation by “uid=Replication Manager” etc. and ADD/MOD ops done by it on consumer side). We might not manually inspect these each run, but storing them is invaluable when debugging.

We also ensure that container and host times are aligned to avoid confusion in log timestamps. If the Podman VM uses UTC and host uses local time, the logs might be UTC (389 DS usually uses local system time in logs). It’s fine as long as consistent.

Container Resource Limits and Debugging: Observability also includes making sure containers have sufficient resources. The Podman machine was allocated 8GB, which should be plenty for 4 DS instances with small data. If needed, we can adjust 389 DS configuration for file descriptors or threads. The container entrypoint auto-tunes some things (for example, sets ulimit and certain database settings based on cgroup limits) ￼. If we hit any limits (like “Too many open files”), we might increase the ulimit via Compose (there is ulimits: in compose where we could set nofile: 10240). We haven’t set it explicitly, but it’s good to note.

Real-time Observation: We could use podman logs -f to watch a container’s output or tail the logs in volumes during a test. This is outside Ansible, but useful during development. The structured logs and our healthcheck help ensure we can detect if something goes wrong (e.g., if a container crashes, podman ps will show it exited and healthcheck won’t matter then).

9. Makefile Targets and Test Matrix

To simplify running the testbed, we use a Makefile to define common operations that support both DEV and INT environments:

.PHONY: up down mesh reset_soft reset_hard logs test up_dev up_int

# Environment-specific targets
up_dev:   ## Start DEV environment (persistent containers)
	@podman-compose up -d
	@ansible-playbook -i inventories/lab/hosts.yml -e env_type=dev provision.yml

up_int:   ## Start INT environment (ephemeral containers)
	@podman-compose up -d
	@ansible-playbook -i inventories/lab/hosts.yml -e env_type=int provision.yml

up: up_dev  ## Default to DEV environment

mesh: ## Configure replication topology (after up)
	@ansible-playbook -i inventories/lab/hosts.yml replicate.yml

verify: ## Verify replication and schema (after mesh)
	@ansible-playbook -i inventories/lab/hosts.yml verify.yml

test: ## Full test run (up -> mesh -> verify -> logs)
	@$(MAKE) up
	@$(MAKE) mesh
	@$(MAKE) verify
	@$(MAKE) logs

test_dev: ## Full DEV test run
	@$(MAKE) up_dev
	@$(MAKE) mesh
	@$(MAKE) verify
	@$(MAKE) logs

test_int: ## Full INT test run (ephemeral, no restarts allowed)
	@$(MAKE) up_int
	@$(MAKE) mesh
	@$(MAKE) verify
	@$(MAKE) logs

down: ## Stop and remove containers (keeps volumes for DEV)
	@podman-compose down

reset_soft: ## Reload data from backup, preserve config & certs (DEV only)
	@ansible-playbook -i inventories/lab/hosts.yml reset_soft.yml

reset_hard: ## Destroy and re-create everything from scratch
	@podman-compose down -v
	@podman network rm dsnet || true
	@sudo rm -rf /srv/389ds-lab/data/* /srv/389ds-lab/logs/*
	@$(MAKE) up

logs: ## Collect logs and bundle into artifact
	@ansible-playbook -i inventories/lab/hosts.yml collect_logs.yml

Explanation:
	•	up_dev: Brings up DEV environment with persistent bind mounts. Allows restarts and preserves state.
	•	up_int: Brings up INT environment with tmpfs volumes. No restarts allowed after seeding begins.
	•	up: Default target (uses DEV environment).
	•	test_dev/test_int: Environment-specific full test runs with appropriate lifecycle management.
	•	reset_soft: Only applicable to DEV environment - reloads data while preserving config/certs.
	•	reset_hard: Destroys everything and rebuilds (works for both environments).
	•	logs: In DEV, collects from persistent bind mounts. In INT, exports artifacts before teardown.

We include descriptions for each target (so make help could list them). Also we ensure commands like podman network rm dsnet ignore errors (in case it’s already gone). The sudo rm -rf is only needed if the VM’s mount is somehow root-owned; in our case, likely not, since directories in /srv/389ds-lab were created by our user via mounts.

Test Matrix: Our setup is parameterized to allow different scenarios across both DEV and INT environments:

**Environment Matrix Combinations:**
	•	DEV with persistent bind mounts: For development, iterative testing, and debugging.
	•	INT with tmpfs volumes: For clean integration testing with deterministic seeding and artifact export.
	•	Both environments support the same topology variations and configuration options.

**Topology Variations:**
	•	Number of consumers (N): By editing the inventory (e.g., adding c3, c4 with new replica IDs) and adjusting group_vars, the playbooks handle arbitrary N (each consumer adds agreements on each supplier).
	•	Topology shape: Setting topology="mesh_all_suppliers" treats all nodes as suppliers with full mesh replication. Each pair gets bidirectional agreements (4 nodes = 12 total agreements).
	•	TLS on/off: Setting enable_tls=false skips certificate generation and uses LDAP (389) for agreements. Useful for baseline testing or TLS troubleshooting.

**Environment-Specific Considerations:**
	•	DEV: Supports reset_soft for data reloading while preserving config/certs. Allows container restarts for debugging.
	•	INT: Enforces no restarts after seeding (dirsrv_no_restart=true). All artifacts must be exported before teardown. Uses deterministic seeding sequence.
	•	Both: Support same timeouts, health checks, and acceptance criteria.

**Advanced Testing Scenarios:**
	•	Latency/Failure injection: Use tc in Podman VM for network simulation:
	  ```
	  sudo tc qdisc add dev cni-podman0 root netem delay 100ms 10ms
	  ```
	•	Time sync validation: Ensure Podman VM has NTP enabled (max 2s skew between nodes).
	•	Resource limits: Adjust Podman machine CPU/memory or container ulimits for performance testing.

**CI Integration:**
	•	Run make test_dev for development validation.
	•	Run make test_int for clean integration testing with SLA enforcement.
	•	Both support the same acceptance criteria: convergence within timeouts, no restarts in INT, artifact export/persistence.

10. Troubleshooting Guide

Despite automation, issues can arise. Below we list common symptoms, likely causes, and steps to diagnose and fix them:
	•	Container won’t start / unhealthy (LDAPI not ready):
	•	Symptoms: podman ps shows a container constantly restarting or healthcheck failing. podman logs <container> shows no “Server started” message or shows an error.
	•	Likely causes: The DS instance failed to initialize. Possibly the volume permissions are wrong (e.g., SELinux denial or owner mismatch), or the instance creation hit an error. Or the container entrypoint might be stuck waiting for something.
	•	Diagnosis: Run podman logs <name> to see output. Check <instance>/errors log in logs/ volume for clues. If you see “Failed to create database environment” or similar, it could be a file permission issue (e.g., if we didn’t use :Z on volumes for SELinux, or if UID mismatch). If there’s an NSS database error, perhaps the cert DB is corrupted or we imported certs incorrectly.
	•	Fix: Ensure the volumes are empty on first run (reset_hard if not). Ensure DS_DM_PASSWORD is set (if not, the container might generate a random password and hang waiting for input – though unlikely, as it usually wouldn’t hang). If SELinux is on (on a Linux host), the :Z flag covers it. On macOS, no SELinux. Also check memory: if the VM is memory constrained, the process might be OOM-killed; 8GB is generous, but if containers keep restarting, check dmesg in VM for OOM. If it’s permission, ls -l the mounted dirs to ensure they are owned by the right user (the container might run as dirsrv user UID 389 by default; if volumes are root-owned, could be an issue. Upstream container runs as root initially and drops to dirsrv for process, so it should be able to chown during setup). For unhealthy but running containers, the health script might be failing to detect readiness. In that case, exec into container (podman exec -it s1 /bin/bash) and manually check: does /var/run/slapd-s1.socket exist? Does dsctl s1 status return “running”? If the socket exists but dsctl hangs, the server might be up but unresponsive (e.g., stuck indexing). Give it more time or check top inside container to see CPU usage. If truly hung, consider killing and looking at core (advanced debugging).
	•	Related: If container fails immediately with exit code, podman logs should show cause (like “address already in use” if somehow port 389 is taken, though in VM unlikely unless leftover process).
	•	Replication not working (RUV divergence or no sync):
	•	Symptoms: After running the replication playbook, data is not replicating. The dsconf replication status shows agreements in error or not up to date. RUV on one server doesn’t list the other’s ID. For instance, nsds5replicaLastUpdateStatus on an agreement says “error -2: cannot connect” ￼.
	•	Likely causes: TLS connection issues or authentication issues are common. If agreements can’t connect: maybe the hostname can’t be resolved, or the TLS handshake failed (cert issues), or wrong credentials.
	•	Diagnosis: Check error logs on supplier and consumer around the time of replication init. On the supplier side, you might see “LDAP error: Can’t connect to replica (error -2)” ￼ indicating a low-level connection failure. On consumer, you might see an incoming connection then an SSL error. Use ldapsearch from supplier container to consumer: e.g., podman exec s1 ldapsearch -H ldaps://c1.dsnet.test -x -D "cn=Replication Manager,cn=config" -w Changeme!23 -s base -b "" defaultnamingcontext. If that fails, it isolates the problem to connectivity or auth. Possible specific causes:
	•	Name resolution: From s1 container, does getent hosts c1.dsnet.test return the IP? If not, DNS alias might not be working. Perhaps the dnsname plugin container isn’t running. (Though typically netavark spawns Aardvark DNS automatically.) If broken, consider using --ip and adding /etc/hosts entries in compose as fallback. For quick fix, you could try using IP addresses in agreements (not ideal for TLS unless you add IP as SAN in certs). Better to fix DNS: ensure the network was created with dnsname enabled (we did) and that containers connected to it at startup (they did).
	•	TLS certificate SAN mismatch: If replication is failing with TLS errors, one possibility is that the consumer is checking the supplier’s cert hostname. 389 DS by default does check the peer’s hostname against the cert (nsSSLCheckHostName=on). If, for example, our agreement on s1 points to “c1.dsnet.test” but c1’s cert’s CN is “c1.dsnet.test” (that’s correct). If we had used short name or IP, it would fail. So ensure agreements use FQDN matching the cert SAN. Also, each server must trust the CA: verify certutil -L -d sql:/etc/dirsrv/slapd-s1/certs shows the CA with “CT,C,C”. If not, then s1 won’t trust c1’s cert and vice versa. We imported, but if a step was missed on one, replication binds will fail with TLS error. The error log would show something like “SSL peer cannot verify your certificate” or “certificate not trusted”. If that happens, rerun the TLS role for that host or manually import the CA cert with certutil (as shown earlier).
	•	Wrong credentials: If the replication manager password didn’t get set the same on both sides, e.g., if maybe on consumers the create-manager step didn’t run so they don’t have that entry (though the supplier wouldn’t know until it tries to bind). In the consumer’s error log you might see a BIND failure for uid=Replication Manager (if it fell back to trying as a normal bind and the entry doesn’t exist or password wrong). To fix, you could re-run dsconf replication create-manager on the consumer with the expected password. Alternatively, use Directory Manager as bind DN in agreements temporarily to see if that works (not recommended long-term, but for debugging, if DM bind works, then it’s an issue with replication user).
	•	Replica ID collision: If by mistake two servers got the same replica ID, replication can behave oddly (updates from both appear as same source, causing conflicts in CSN). Check each server’s cn=replica entry via dsconf replication get or ldapsearch for nsds5replicaid. If any duplicates, that’s a config mistake – change one (requires disable & re-enable replication or editing dse.ldif carefully).
	•	Changelog not enabled: If a supplier’s changelog wasn’t created, it can’t provide updates. On supplier’s error log, look for changelog5 plugin messages. If it’s missing, ensure dsconf replication enable was run on that supplier.
	•	Replication agreements not created or enabled: Ensure the agreements exist in the DIT. Use ldapsearch -D "cn=directory manager" -w password -b "cn=replica,cn={{suffix}},cn=mapping tree,cn=config" objectClass=nsDS5ReplicationAgreement nsds5replicaHost. That will list agreements defined. If one is missing (maybe playbook logic skipped one), add it.
	•	Time skew / CSN issues: In rare cases, if one server’s clock was far ahead at config time, its CSNs might be future-dated and other servers won’t catch up until time passes. Check system times (date on each container). If there’s >5 minutes difference, that could be an issue. Sync time, then possibly reinitialize replication to reset CSNs.
	•	Fix: Based on diagnosis: fix DNS resolution (recreate network or use alias/hosts), fix cert trust or SAN issues (reissue cert with correct SAN, or set nsslapd-sslcheckhostnames: off in cn=config as a workaround to not require exact name match – not recommended except for quick test), fix credentials (reset replication manager passwords to known value on all and update agreements if needed).
	•	Slow replication or missing updates under load:
	•	Symptoms: Small changes replicate but large LDIF bulk adds do not, or high latency before consumers update.
	•	Likely causes: Perhaps default flow control or window size is limiting throughput ￼ ￼. Or if lots of mods, the changelog trimming might be interfering.
	•	Diagnosis: Check dsconf replication monitor output for backlog. Check if network latency is an issue (if injecting delay intentionally, that’s expected). Possibly logs show “supplier busy” messages, which is flow control kicking in. 389 DS has tunables like --flow-control-window and --busy-wait-time on agreements ￼ ￼. We left them default. For tests, defaults are fine.
	•	Fix: If needed, we could adjust those via dsconf repl-agmt set. Also ensuring the VM has enough CPU, etc. If performing very large initial loads, consider doing offline LDIF import on each and then enable replication to sync delta.
	•	Certificate issues (TLS/SSL):
	•	Symptoms: ldapsearch -H ldaps://... fails with certificate errors, or replication failing as above.
	•	Likely cause: CA not trusted by client, or server presenting wrong cert.
	•	Diagnosis: Use openssl s_client -connect s1.dsnet.test:636 -CAfile ca.crt from the Podman VM. This will show the certificate chain and whether it’s trusted. If it says Verify return code: 0 (ok) then the cert is fine. If not, it will say what’s wrong (e.g., unable to verify). If the server presented a different cert (maybe the container auto-created one if our import failed), the subject/CN might not match expected. openssl s_client output will show the server cert’s subject. If it’s something like “CN=localhost”, then our intended cert wasn’t in use. That means our nsSSLPersonalitySSL config didn’t apply – maybe we forgot to restart the server after adding cert? Solution: restart that container or use dsctl <inst> restart. After restart it should pick up the new cert.
	•	Fix: Ensure the nsSSLPersonalitySSL attribute exactly matches the cert nickname. It’s case-sensitive. If in doubt, use certutil -L to list nicknames; set the attribute to that. Restart. Also, double-check we set nsslapd-securePort: 636. If the server isn’t listening on 636 at all, then our TLS config didn’t apply; run dsconf get-config | grep securePort. If missing, set it and restart.
	•	DNS name collisions across runs:
	•	Symptoms: On a rerun, containers can’t start or have weird DNS resolution issues.
	•	Cause: If the dsnet network wasn’t removed and still had DNS entries from old containers, new ones might conflict. Or if you have two podman machine VMs both using dsnet.test domain in hosts, could confuse.
	•	Fix: Always do podman network rm dsnet if you suspect stale config (our reset_hard does that). Also avoid running two instances of the environment simultaneously on one VM (since they’d share the dsnet network). If needed, parameterize the network name (like use an env var to name it differently per run).
	•	389 DS specific issues:
	•	e.g., “Max thread limit reached” in error log – increase nsslapd-maxthreads in config (though default 30 is usually fine unless heavy concurrency).
	•	Memory leaks or high CPU: if a bug in 389 DS triggers at load, consider updating to latest image (ghcr latest corresponds to latest upstream code; if a bug is suspected, try a specific version tag or check 389-ds issues).
	•	Import/Export problems: if using db2bak and bak2db in soft reset, ensure to quiesce (stop updates) and maybe disable replication temporarily during restore.

Precise triage steps:
	•	To check if a replication agreement is active: dsconf replication status --suffix dc=example,dc=com --bind-dn "cn=Replication Manager,cn=config" --bind-passwd "Changeme!23" ldap://s1 – this will actually attempt to bind to consumers and report status. If an agreement is down, it prints an error.
	•	To see replication topology: dsconf replication monitor on any supplier gives a report of all replicas and their status ￼.
	•	To get the RUV: dsconf replication get-ruv --suffix dc=example,dc=com ldap://c1 outputs the RUV entry, which you can examine for missing IDs.
	•	If data mismatch: do a manual full init: dsconf replication initialize --from s1 --suffix dc=example,dc=com ldap://c2 (there’s a slight syntax difference in dsconf 2.x, but essentially).
	•	Use ldapsearch on each server’s cn=config subtree to verify that cn=changelog5 exists on suppliers and cn=replica entries look correct.

By following this guide, one should be able to stand up the macOS-hosted Podman testbed and quickly diagnose any issues in replication setup or runtime. The emphasis on deterministic configuration (fixed hostnames, known certs, stable ports) and robust logging/health checks is intended to make the test environment first-class: easy to spin up, tear down, and introspect, thus accelerating development and troubleshooting of 389-DS replication features.
