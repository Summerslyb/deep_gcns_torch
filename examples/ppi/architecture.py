import torch
from torch.nn import Linear as Lin, Sequential as Seq
from gcn_lib.sparse import MultiSeq, MLP, GraphConv, ResDynBlock, DenseDynBlock, ResGraphBlock, DenseGraphBlock


class DynDeepGCN(torch.nn.Module):
    def __init__(self, opt):
        super(DynDeepGCN, self).__init__()
        channels = opt.n_filters
        k = opt.kernel_size
        act = opt.act
        norm = opt.norm
        knn = opt.knn
        bias = opt.bias
        epsilon = opt.epsilon
        # TODO: stochastic
        stochastic = False
        conv = opt.conv
        c_growth = channels

        self.n_blocks = opt.n_blocks
        self.head = GraphConv(opt.in_channels, channels, conv, act, norm, bias)

        if opt.block.lower() == 'res':
            self.backbone = MultiSeq(*[ResDynBlock(channels, k, i % 8 + 1, conv, act, norm, bias,
                                                   stochastic=stochastic, epsilon=epsilon, knn=knn)
                                       for i in range(self.n_blocks-1)])
        elif opt.block.lower() == 'dense':
            self.backbone = MultiSeq(*[DenseDynBlock(channels, k, i % 8 + 1, conv, act, norm, bias,
                                                     stochastic=stochastic, epsilon=epsilon, knn=knn)
                                       for i in range(self.n_blocks-1)])
        else:
            raise NotImplementedError('{} is not implemented. Please check.\n'.format(opt.block))
        self.fusion_block = MLP([channels + c_growth * (self.n_blocks - 1), 1024], act, None, bias)
        self.prediction = MultiSeq(*[MLP([1+channels+c_growth*(self.n_blocks-1), 512, 256], act, None, bias),
                                     MLP([256, opt.n_classes], None, None, bias)])

        self.model_init()

    def model_init(self):
        for m in self.modules():
            if isinstance(m, Lin):
                torch.nn.init.kaiming_normal_(m.weight)
                m.weight.requires_grad = True
                if m.bias is not None:
                    m.bias.data.zero_()
                    m.bias.requires_grad = True

    def forward(self, data):
        x, edge_index, batch = data.x, data.edge_index, data.batch
        feats = [self.head(x, edge_index)]
        for i in range(self.n_blocks-1):
            feats.append(self.backbone[i](feats[-1], batch)[0])
        feats = torch.cat(feats, 1)
        fusion, _ = torch.max(self.fusion_block(feats), 1, keepdim=True)
        out = self.prediction(torch.cat((feats, fusion), 1))
        # return torch.clamp(out, 0, 1)
        return out


class DeepGCNv2(torch.nn.Module):
    """
    static graph

    """
    def __init__(self, opt):
        super(DeepGCNv2, self).__init__()
        channels = opt.n_filters
        act = opt.act
        norm = opt.norm
        bias = opt.bias
        conv = opt.conv
        heads = opt.n_heads
        c_growth = 0
        self.n_blocks = opt.n_blocks
        self.head = GraphConv(opt.in_channels, channels, conv, act, norm, bias, heads)

        res_scale = 1 if opt.block.lower() == 'res' else 0
        if opt.block.lower() == 'dense':
            c_growth = channels
            self.backbone = MultiSeq(*[DenseGraphBlock(channels+i*c_growth, c_growth, conv, act, norm, bias, heads)
                                       for i in range(self.n_blocks-1)])
        else:
            self.backbone = MultiSeq(*[ResGraphBlock(channels, conv, act, norm, bias, heads, res_scale)
                                       for _ in range(self.n_blocks-1)])
        fusion_dims = int(channels * self.n_blocks + c_growth * ((1 + self.n_blocks - 1) * (self.n_blocks - 1) / 2))
        self.fusion_block = MLP([fusion_dims, 1024], act, None, bias)
        self.prediction = Seq(*[MLP([1+fusion_dims, 512], act, norm, bias), torch.nn.Dropout(p=opt.dropout),
                                MLP([512, 256], act, norm, bias), torch.nn.Dropout(p=opt.dropout),
                                MLP([256, opt.n_classes], None, None, bias)])
        self.model_init()

    def model_init(self):
        for m in self.modules():
            if isinstance(m, Lin):
                torch.nn.init.kaiming_normal_(m.weight)
                m.weight.requires_grad = True
                if m.bias is not None:
                    m.bias.data.zero_()
                    m.bias.requires_grad = True

    def forward(self, data):
        x, edge_index, batch = data.x, data.edge_index, data.batch
        feats = [self.head(x, edge_index)]
        for i in range(self.n_blocks-1):
            feats.append(self.backbone[i](feats[-1], edge_index)[0])
        feats = torch.cat(feats, 1)
        fusion, _ = torch.max(self.fusion_block(feats), 1, keepdim=True)
        out = self.prediction(torch.cat((feats, fusion), 1))
        # return torch.clamp(out, -1., 1.
        return out


