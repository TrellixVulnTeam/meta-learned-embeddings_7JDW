import torch.nn as nn
from torch.nn import functional as F
from torch import optim
import torch
from torch.autograd import Variable

import numpy as np
from copy import deepcopy

class MetaLearner(nn.Module):

    def __init__(self, model, args):

        super(MetaLearner, self).__init__()

        self.model = model

        self.meta_lr = args.meta_lr
        self.update_lr = args.update_lr
        self.num_updates = args.num_updates
        self.test_size = args.K * args.num_classes
        self.use_gpu = args.use_gpu

        if self.use_gpu:
            self.model = self.model.cuda()

        self.meta_optim = optim.Adam(self.model.parameters(), lr=self.meta_lr)

        self.num_tasks = args.batch_size

    def forward(self, x_train, y_train, lens_train, x_test, y_test, lens_test):
        # x_train: [num tasks, train size, MAX LENGTH]
        # x_test: [num_tasks, test size, MAX LENGTH]
        # train size = test size = K * num_classes

        losses = [0 for _ in range(self.num_updates + 1)]
        corrects = [0 for _ in range(self.num_updates + 1)]

        for i in range(self.num_tasks):
            logits = self.model(x_train[i], lens_train[i])
            loss = F.cross_entropy(logits, y_train[i])
            grad = torch.autograd.grad(loss, self.model.parameters())
            fast_weights = list(map(lambda p: p[1] - self.update_lr * p[0], zip(grad, self.model.parameters())))
            stored_weights = list(p for p in self.model.parameters())

            # evaluate before
            with torch.no_grad():
                # set size * 2 (binary)
                logits = self.model(x_test[i], lens_test[i])
                loss = F.cross_entropy(logits, y_test[i])
                losses[0] += loss

                pred = F.softmax(logits, dim=1).argmax(dim=1)
                correct = torch.eq(pred, y_test[i]).sum().item()
                corrects[0] += correct

                # update weights
                for updated_param, param in zip(fast_weights, self.model.parameters()):
                    param.data = updated_param

            # evaluate with update
            with torch.no_grad():

                logits = self.model(x_test[i], lens_test[i])
                loss = F.cross_entropy(logits, y_test[i])
                losses[1] += loss

                pred = F.softmax(logits, dim=1).argmax(dim=1)
                correct = torch.eq(pred, y_test[i]).sum().item()
                corrects[1] += correct

                for updated_param, param in zip(fast_weights, self.model.parameters()):
                    param.data = updated_param
            
            for k in range(1, self.num_updates):
                logits = self.model(x_train[i], lens_train[i])
                loss = F.cross_entropy(logits, y_train[i])
                grad = torch.autograd.grad(loss, self.model.parameters())
                fast_weights = list(map(lambda p: p[1] - self.update_lr * p[0], zip(grad, self.model.parameters())))
                for updated_param, param in zip(fast_weights, self.model.parameters()):
                    param.data = updated_param

                logits = self.model(x_test[i], lens_test[i])
                loss = F.cross_entropy(logits, y_test[i])
                losses[k+1] += loss

                with torch.no_grad():
                    pred = F.softmax(logits, dim=1).argmax(dim=1)
                    correct = torch.eq(pred, y_test[i]).sum().item()
                    corrects[k+1] += correct

        loss = losses[-1] / self.num_tasks
        loss = Variable(loss, requires_grad=True)

        # restore original model weights
        for updated_param, param in zip(stored_weights, self.model.parameters()):
            param.data = updated_param

        # meta learning step
        self.meta_optim.zero_grad()
        loss.backward()
        self.meta_optim.step()

        losses = np.array(losses) / (self.test_size * self.num_tasks)
        accs = np.array(corrects) / (self.test_size * self.num_tasks)

        return losses, accs
