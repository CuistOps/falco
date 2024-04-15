"""Deploy nodes for a Kubernetes cluster on OpenStack using Pulumi."""

import pulumi
from pulumi_openstack import compute
from pulumi_openstack import networking

config = pulumi.Config()

# Create a network and subnet
lan_net = networking.Network("nodes-net", admin_state_up=True)
subnet = networking.Subnet("nodes-subnet",
    network_id=lan_net.id,
    cidr=config.get('subnet_cidr'),
    ip_version=4,
    dns_nameservers=["1.1.1.1", "9.9.9.9"]
)

# Create a router (to connect the subnet to internet)
router = networking.Router("nodes-router", admin_state_up=True, external_network_id=config.get('floating_ip_net_id'))
router_interface1 = networking.RouterInterface("routerInterface1",
    router_id=router.id,
    subnet_id=subnet.id)

# Upload our public key to OpenStack
admin_keypair = compute.Keypair("admin-keypair", public_key=config.get('public_key'))

# Generate a new keypair to let the admin instance connect to the other instances
node_keypair = compute.Keypair("nodes-keypair")
pulumi.export("nodes_keypair", node_keypair.private_key)

# Security groups to allow ssh for the admin instance
ssh_external_secgroup = networking.SecGroup("ssh_external", description="My neutron security group")
networking.SecGroupRule("allow-ssh-external",
    direction="ingress",
    ethertype="IPv4",
    port_range_max=22,
    port_range_min=22,
    protocol="tcp",
    remote_ip_prefix="0.0.0.0/0",
    security_group_id=ssh_external_secgroup.id)

# Security group for the nodes (allow all traffic in the subnet)
node_secgroup = networking.SecGroup("node_secgroup", description="My neutron security group")
networking.SecGroupRule("ingress-allow-everything-in-lan",
    direction="ingress",
    ethertype="IPv4",
    remote_ip_prefix=config.get('subnet_cidr'),
    security_group_id=node_secgroup.id)

networking.SecGroupRule("egress-allow-everything-in-lan",
    direction="egress",
    ethertype="IPv4",
    remote_ip_prefix=config.get('subnet_cidr'),
    security_group_id=node_secgroup.id)


admin_instance = compute.Instance("admin-instance",
                                        flavor_name=config.get('flavor_admin'),
                                        image_name=config.get('image_admin'),
                                        networks=[ {"name": lan_net.name}],
                                        key_pair=admin_keypair.name,
                                        security_groups=[ssh_external_secgroup.name, node_secgroup.name],
                                        opts=pulumi.ResourceOptions(depends_on=[node_keypair, router])
                                 )

floating_ip_admin = compute.FloatingIp("admin-instance", pool="ext-floating1")

floating_ip_admin_associate = compute.FloatingIpAssociate("floating-ip-admin",
        floating_ip=floating_ip_admin.address,
        instance_id=admin_instance.id,
        fixed_ip=admin_instance.networks[0].fixed_ip_v4)
    
pulumi.export("admin_external_ip", floating_ip_admin.address)

nodes = {}
for i in range(int(config.get('num_nodes'))):
    instance_name = f"node-{i}"
    instance = compute.Instance(instance_name,
                                                flavor_name=config.get('flavor_node'),
                                                image_name=config.get('image_node'),
                                                networks=[{"name": lan_net.name}],
                                                key_pair=node_keypair.name,
                                                security_groups=[node_secgroup.name],
                                                opts=pulumi.ResourceOptions(depends_on=[subnet, node_secgroup])
                                            )
    nodes[instance_name] = {"name" : instance.name, "ip" : instance.access_ip_v4, "id" : instance.id}

pulumi.export("nodes", nodes)