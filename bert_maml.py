import torch.nn as nn
from torch.nn import functional as F
from torch import optim
import torch
from torch.autograd import Variable

import numpy as np
from copy import deepcopy

## TENSORBOARD LOGGING ##
from tensorboardX import SummaryWriter

class MetaLearner(nn.Module):

    def __init__(self, model, args):

        super(MetaLearner, self).__init__()

        self.model = model

        self.args = args

        self.meta_lr = args.meta_lr
        self.update_lr = args.update_lr
        self.num_updates = args.num_updates
        self.test_size = args.K
        self.use_gpu = args.use_gpu

        if self.use_gpu:
            self.model = self.model.cuda()

        self.meta_optim = optim.Adam(self.model.parameters(), lr=self.meta_lr)

    def load_weights(self, parameters):
        # update weights
        for updated_param, param in zip(parameters, self.model.parameters()):
            param.data.copy_(updated_param)

    def forward(self, x_train, y_train, lens_train, x_test, y_test, lens_test, tbx, num_tensorboard_steps, evaluate):
        # x_train: [num tasks, train size, MAX LENGTH]
        # x_test: [num_tasks, test size, MAX LENGTH]
        # train size = test size = K

        losses = [0 for _ in range(self.num_updates + 1)]
        corrects = [0 for _ in range(self.num_updates + 1)]

        self.model.zero_grad()
        stored_weights = list(p.data for p in self.model.parameters())

        for i in range(len(x_train)):

            # run model on train data
            logits = self.model(x_train[i], lens_train[i])
            loss = F.cross_entropy(logits, y_train[i])
            grad = torch.autograd.grad(loss, self.model.parameters())
            fast_weights = list(map(lambda p: p[1] - self.update_lr * p[0], zip(grad, self.model.parameters())))

            ## tb records loss ##
            loss_val = loss
            tbx.add_scalar('train/loss', loss_val, num_tensorboard_steps)

            # evaluate on test data before gradient update
            with torch.no_grad():
                # set size * 2 (binary)
                logits = self.model(x_test[i], lens_test[i])
                loss = F.cross_entropy(logits, y_test[i])
                losses[0] += loss

                pred = F.softmax(logits, dim=1).argmax(dim=1)
                correct = torch.eq(pred, y_test[i]).sum().item()
                corrects[0] += correct


            # update weights
            self.load_weights(fast_weights)

            # evaluate on test data after gradient update
            with torch.no_grad():

                logits = self.model(x_test[i], lens_test[i])
                loss = F.cross_entropy(logits, y_test[i])
                losses[1] += loss

                pred = F.softmax(logits, dim=1).argmax(dim=1)
                correct = torch.eq(pred, y_test[i]).sum().item()
                corrects[1] += correct



            # for k in range(1, self.num_updates):
            #     logits = self.model(x_train[i], lens_train[i])
            #     loss = F.cross_entropy(logits, y_train[i])
            #     grad = torch.autograd.grad(loss, self.model.parameters())
            #     fast_weights = list(map(lambda p: p[1] - self.update_lr * p[0], zip(grad, self.model.parameters())))
            #     for updated_param, param in zip(fast_weights, self.model.parameters()):
            #         param.data.copy_(updated_param)

            #     logits = self.model(x_test[i], lens_test[i])
            #     loss = F.cross_entropy(logits, y_test[i])
            #     losses[k+1] += loss

            #     pred = F.softmax(logits, dim=1).argmax(dim=1)
            #     correct = torch.eq(pred, y_test[i]).sum().item()
            #     corrects[k+1] += correct

            # restore original model weights
            self.load_weights(stored_weights)

        loss = losses[-1] / len(x_test)
        loss = Variable(loss, requires_grad=True)

        self.meta_optim.zero_grad()

        # meta learning step
        if not evaluate:
            loss.backward()
            self.meta_optim.step()

        losses = np.array(losses) / (len(x_test[0]) * len(x_test))
        accs = np.array(corrects) / (len(x_test[0]) * len(x_test))

        ## tb records loss ##
        before_loss_val = losses[0]
        tbx.add_scalar('test/before_gradient_update/loss', before_loss_val, num_tensorboard_steps)
        before_acc = accs[0]
        tbx.add_scalar('test/before_gradient_update/acc', before_acc, num_tensorboard_steps)

        after_loss_val = losses[1]
        tbx.add_scalar('test/after_gradient_update/loss', after_loss_val, num_tensorboard_steps)
        after_acc = accs[1]
        tbx.add_scalar('test/after_gradient_update/acc', after_acc, num_tensorboard_steps)
        return losses, accs
