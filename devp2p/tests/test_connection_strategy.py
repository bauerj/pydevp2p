import time
import networkx as nx
import matplotlib.pyplot as plt
import devp2p.kademlia
from test_kademlia_protocol import test_many
from collections import OrderedDict
import random
import statistics

random.seed(42)


class CNodeBase(object):

    """
    to implement your conenction strategy override
        .select_targets (must)
        .connect_peers
    """
    k_max_node_id = devp2p.kademlia.k_max_node_id

    def __init__(self, proto, network, min_peers=5, max_peers=10):
        self.proto = proto
        self.network = network
        self.min_peers = min_peers
        self.max_peers = max_peers
        self.connections = []
        self.id = proto.this_node.id
        # list of dict(address=long, tolerance=long, connected=bool)
        # address is the id : long
        self.targets = list()

    def distance(self, other):
        return self.id ^ other.id

    def receive_connect(self, other):
        if len(self.connections) == self.max_peers:
            return False
        else:
            assert other not in self.connections
            self.connections.append(other)
            return True

    def receive_disconnect(self, other):
        assert other in self.connections
        self.connections.remove(other)
        # FIXME find associated target and set it to t.connected = False

    def find_targets(self):
        "call find node to fill buckets with addresses close to the target"
        for t in self.targets:
            self.proto.find_node(t['address'])
            self.network.process()

    def connect_peers(self, max_connects=0):
        """
        override to deal with situations where
            - you enter the method and have not enough slots to conenct your targets
            - your targets don't want to connect you
            - targets are not within the tolerace
            ...
        """
        assert self.targets
        num_connected = 0
        # connect closest node to target id
        for t in (t for t in self.targets if not t['connected']):
            if len(self.connections) >= self.max_peers:
                break
            for knode in self.proto.routing.neighbours(devp2p.kademlia.Node.from_id(t['address'])):
                assert isinstance(knode, devp2p.kademlia.Node)
                # assure within tolerance
                if knode.id_distance(t['address']) < t['tolerance']:
                    # make sure we are not connected yet
                    remote = self.network[knode.id]
                    if remote not in self.connections:
                        if remote.receive_connect(self):
                            t['connected'] = True
                            self.connections.append(remote)
                            num_connected += 1
                            if max_connects and num_connected == max_connects:
                                return num_connected
                            break
        return num_connected

    def setup_targets(self):
        """
        calculate select target distances, addresses and tolerances
        """
        for i in range(self.min_peers):
            self.targets.append(dict(address=0, tolerance=0, connected=False))
            # NOT IMPLEMENTED HERE


class CNodeRandomClosesestNodeGivenBucket(CNodeBase):

    """Alex:
    onNodeAddedToTable(node)
      dist = distance(node, self)
      tcpEvict = peersByDistance[dist].last
      if !tcpEvict
        connect(node)
      else if tcpEvict.uptime < 30 && tcpEvict.totalUptime < 300
        tryConnect(node, tcpEvict)
    """
    pass


class CNodeRandom(CNodeBase):

    def setup_targets(self):
        """
        connects random nodes
        """
        for i in range(self.min_peers):
            distance = random.randint(0, self.k_max_node_id)
            address = (self.id + distance) % (self.k_max_node_id + 1)
            tolerance = self.k_max_node_id / self.min_peers
            self.targets.append(dict(address=address, tolerance=tolerance, connected=False))


class CNodeRandomClose(CNodeBase):

    def setup_targets(self):
        """
        connects random nodes in the neighbourhood only
        """
        neighbourhood_distance = self.k_max_node_id * 0.05
        for i in range(self.min_peers):
            distance = random.randint(0, neighbourhood_distance)
            address = (self.id + distance) % (self.k_max_node_id + 1)
            tolerance = self.k_max_node_id / self.min_peers
            self.targets.append(dict(address=address, tolerance=tolerance, connected=False))


class CNodeRandomClosest(CNodeBase):

    def setup_targets(self):
        """
        connects the closest neighbours only
        """
        for i in range(self.min_peers):
            address = (self.id + i) % (self.k_max_node_id + 1)
            tolerance = self.k_max_node_id / self.min_peers
            self.targets.append(dict(address=address, tolerance=tolerance, connected=False))


class CNodeEqualFingers(CNodeBase):

    def setup_targets(self):
        """
        connects random nodes according to a dht routing
        """
        for i in range(self.min_peers):
            distance = (i + 1) * self.k_max_node_id / (self.min_peers + 1)
            address = (self.id + distance) % (self.k_max_node_id + 1)
            tolerance = distance
            self.targets.append(dict(address=address, tolerance=tolerance, connected=False))


class CNodeKademlia(CNodeBase):

    def setup_targets(self):
        """
        connects random nodes according to a dht routing
        """
        distance = self.k_max_node_id
        for i in range(self.min_peers):
            distance /= 2
            address = (self.id + distance) % (self.k_max_node_id + 1)
            tolerance = distance
            self.targets.append(dict(address=address, tolerance=tolerance, connected=False))


class CNodeKademliaAndClosest(CNodeBase):

    def setup_targets(self):
        """
        connects random nodes in the neighbourhood, then kademlia
        """
        half = self.min_peers / 2
        for knode in self.proto.routing.neighbours(self.proto.this_node)[:half]:
            address = knode.id
            tolerance = knode.id
            self.targets.append(dict(address=address, tolerance=tolerance, connected=False))

        distance = self.k_max_node_id
        for i in range(self.min_peers - half):
            distance /= 2
            address = (self.id + distance) % (self.k_max_node_id + 1)
            tolerance = distance
            self.targets.append(dict(address=address, tolerance=tolerance, connected=False))


def analyze(network):
    G = nx.Graph()

    def weight(a, b):
        """
        Weight of edge. In dot,
        the heavier the weight, the shorter, straighter and more vertical the edge is.
        For other layouts, a larger weight encourages the layout to make the edge length
        closer to that specified by the len attribute.
        """
        # same node is weight == 1
        return (1 - a.distance(b) / devp2p.kademlia.k_max_node_id) * 10

    for node in network.values():
        for r in node.connections:
            G.add_edge(node, r, weight=weight(node, r))

    num_peers = [len(n.connections) for n in network.values()]
    metrics = OrderedDict(num_nodes=len(network))
    metrics['max_peers'] = max(num_peers)
    metrics['min_peers'] = min(num_peers)
    metrics['avg_peers'] = sum(num_peers) / len(num_peers)

    # calc shortests paths
    # lower is better
    if nx.is_connected(G):
        print 'calculating avg_shortest_path'
        avg_shortest_paths = []
        for node in G:
            path_length = nx.single_source_shortest_path_length(G, node)
            avg_shortest_paths.append(sum(path_length.values()) / len(path_length))

        metrics['avg_shortest_path'] = statistics.mean(avg_shortest_paths)
        metrics['rsd_shortest_path'] = statistics.stdev(
            avg_shortest_paths) / metrics['avg_shortest_path']

    try:
        # Closeness centrality at a node is 1/average distance to all other nodes.
        # higher is better
        print 'calculating closeness centrality'
        vs = nx.closeness_centrality(G).values()
        metrics['min_closeness_centrality'] = min(vs)
        metrics['avg_closeness_centrality'] = statistics.mean(vs)
        metrics['rsd_closeness_centrality'] = statistics.stdev(
            vs) / metrics['avg_closeness_centrality']

        # The load centrality of a node is the fraction of all shortest paths that
        # pass through that node
        # Daniel:
        # I recommend calculating (or estimating) the centrality of each node and making sure that
        # there are no nodes with much higher centrality than the average.
        # lower is better
        print 'calculating load centrality'
        vs = nx.load_centrality(G).values()
        metrics['max_load_centrality'] = max(vs)
        metrics['avg_load_centrality'] = statistics.mean(vs)
        metrics['rsd_load_centrality'] = statistics.stdev(vs) / metrics['avg_load_centrality']

        print 'calculating edge_connectivity'
        # higher is better
        metrics['edge_connectivity'] = nx.edge_connectivity(G)

        print 'calculating diameter'
        # lower is better
        metrics['diameter '] = nx.diameter(G)

    except nx.exception.NetworkXError as e:
        metrics['ERROR'] = -1
    return metrics


def draw(G, metrics=dict()):
    """
    dot - "hierarchical" or layered drawings of directed graphs. This is the default tool to use if edges have directionality.

    neato - "spring model'' layouts. This is the default tool to use if the graph is not too large (about 100 nodes) and you don't know anything else about it. Neato attempts to minimize a global energy function, which is equivalent to statistical multi-dimensional scaling.

    fdp - "spring model'' layouts similar to those of neato, but does this by reducing forces rather than working with energy.

    sfdp - multiscale version of fdp for the layout of large graphs.

    twopi - radial layouts, after Graham Wills 97. Nodes are placed on concentric circles depending their distance from a given root node.

    circo - circular layout, after Six and Tollis 99, Kauffman and Wiese 02. This is suitable for certain diagrams of multiple cyclic structures, such as certain telecommunications networks.

    """
    print 'layouting'

    text = ''
    for k, v in metrics.items():
        text += '%s: %.4f\n' % (k.ljust(max(len(x) for x in metrics.keys())), v)

    print text
    #pos = nx.graphviz_layout(G, prog='dot', args='')
    pos = nx.spring_layout(G)
    plt.figure(figsize=(8, 8))
    nx.draw(G, pos, node_size=20, alpha=0.5, node_color="blue", with_labels=False)
    plt.text(0.02, 0.02, text, transform=plt.gca().transAxes)  # , font_family='monospace')
    plt.axis('equal')
    outfile = 'network_graph.png'
    plt.savefig(outfile)
    print 'saved visualization to', outfile
    plt.ion()
    plt.show()
    while True:
        time.sleep(0.1)


def simulate(node_class, set_num_nodes=20, set_min_peers=7, set_max_peers=14):
    print 'running simulation', node_class.__name__, \
        dict(num_nodes=set_num_nodes, min_peers=set_min_peers, max_peers=set_max_peers)

    print 'bootstrapping discovery protocols'
    kademlia_protocols = test_many(set_num_nodes)

    # create ConnectableNode instances
    print 'executing connection strategy'
    network = OrderedDict()  # node.id -> Node
    # .process executes all messages on the network
    network.process = lambda: kademlia_protocols[0].wire.process(kademlia_protocols)

    # wrap protos in connectable nodes and map via network
    for p in kademlia_protocols:
        cn = node_class(p, network, min_peers=set_min_peers, max_peers=set_max_peers)
        network[cn.id] = cn

    print 'setup targets'
    # setup targets
    for cn in network.values():
        cn.setup_targets()

    print 'lookup targets'
    # lookup targets
    for cn in network.values():
        cn.find_targets()

    print 'connect peers'
    # connect peers (one client per round may connect)
    while True:
        n_connects = 0
        for cn in network.values():
            n_connects += cn.connect_peers(max_connects=1)
        if n_connects == 0:
            break

    metrics = analyze(network)
    return metrics


def print_results(results=[]):
    labels = results[0].keys()
    print '\t'.join(labels)
    f = lambda x: str(x) if isinstance(x, (int, str)) else ('%.4f' % x)  # .replace('.', ',')
    for r in results:
        print '\t'.join(f(r.get(k, 'n/a')) for k in labels)


def main(num_nodes):
    klasses = [CNodeRandom, CNodeRandomClose,
               CNodeEqualFingers, CNodeKademlia,
               CNodeKademliaAndClosest]
    klasses = [CNodeRandomClosest]

    results = []
    for min_peers in (5, 7, 9):
        max_peers = min_peers * 2
        for node_class in klasses:
            p = OrderedDict(node_class=node_class)
            p.update(OrderedDict(set_num_nodes=num_nodes, set_min_peers=min_peers,
                                 set_max_peers=max_peers))
            metrics = simulate(**p)
            p.update(metrics)
            p['node_class'] = p['node_class'].__name__
            print p
            results.append(p)

    print_results(results)

if __name__ == '__main__':
    # import pyethereum.slogging
    # pyethereum.slogging.configure(config_string=':debug')
    import sys
    if not len(sys.argv) == 2:
        print 'usage:%s <num_nodes>' % sys.argv[0]
        sys.exit(1)
    num_nodes = int(sys.argv[1])
    main(num_nodes)

"""
todos:
    weird results:
        switch to sha3(pubkey) new branch
        speedup find_node (probably expensive sorting)

    colorize nodes being closest to 0, 1/4, 1/2, 3/4 of the id space
    validate graph (assert bidirectional connections, max_peers satisfactions)
    support alanlytics about nodes added to an established network
"""
