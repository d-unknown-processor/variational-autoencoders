import theano
import theano.tensor as T
import numpy as np
import cPickle as pickle

from theano_toolkit import utils as U
from theano_toolkit import updates
from theano_toolkit.parameters import Parameters


def orthogonal_init(*dimensions):
    flat_dimensions = (dimensions[0], np.prod(dimensions[1:]))
    a = np.random.randn(*flat_dimensions)
    u, _, v = np.linalg.svd(a, full_matrices=False)
    # pick the one with the correct shape
    q = u if u.shape == flat_dimensions else v
    q = q.reshape(dimensions)
    return q


def build(P, name, input_size, hidden_size, truncate_gradient=-1):
    name_init_hidden = "init_%s_hidden" % name
    name_init_cell = "init_%s_cell" % name
    P[name_init_hidden] = np.zeros((hidden_size,))
    P[name_init_cell] = np.zeros((hidden_size,))

    _step = build_step(P, name, input_size, hidden_size)

    def lstm_layer(X):
        init_hidden = T.tanh(P[name_init_hidden])
        init_cell = P[name_init_cell]
        init_hidden_batch = T.alloc(init_hidden, X.shape[1], hidden_size)
        init_cell_batch = T.alloc(init_cell, X.shape[1], hidden_size)
        [cell, hidden], _ = theano.scan(
            _step,
            sequences=[X],
            outputs_info=[init_cell_batch, init_hidden_batch],
            truncate_gradient=truncate_gradient
        )
        return cell, hidden
    return lstm_layer


def build_step(P, name, input_size, hidden_size):
    name_W_input = "W_%s_input" % name
    name_W_hidden = "W_%s_hidden" % name
    name_W_cell = "W_%s_cell" % name
    name_b = "b_%s" % name
    P[name_W_input] = 0.1 * np.random.rand(input_size, hidden_size * 4)
    P[name_W_hidden] = 0.1 * np.random.rand(hidden_size, hidden_size * 4)
    P[name_W_cell] = 0.1 * np.random.rand(hidden_size, hidden_size * 3)
    bias_init = np.zeros((4, hidden_size), dtype=np.float32)
    bias_init[1] = 2.5
    P[name_b] = bias_init

    V_if = P[name_W_cell][:, 0 * hidden_size:2 * hidden_size]
    V_o = P[name_W_cell][:, 2 * hidden_size:3 * hidden_size]

    biases = P[name_b]
    b_i = biases[0]
    b_f = biases[1]
    b_c = biases[2]
    b_o = biases[3]

    def _step(x, prev_cell, prev_hid, mask=None):
        # batch_size x hidden_size
        batch_size = x.shape[0]

        # batch_size x 4 x hidden_size
        transformed_x = T.dot(x, P[name_W_input]).reshape(
            (batch_size, 4, hidden_size))
        # batch_size x 4 x hidden_size
        transformed_hid = T.dot(prev_hid, P[name_W_hidden]).reshape(
            (batch_size, 4, hidden_size))
        # batch_size x 2 x hidden_size
        transformed_cell = T.dot(prev_cell, V_if).reshape(
            (batch_size, 2, hidden_size))

        transformed_x_ = transformed_x.dimshuffle(1, 0, 2)
        x_i = transformed_x_[0]
        x_f = transformed_x_[1]
        x_c = transformed_x_[2]
        x_o = transformed_x_[3]   # batch_size x hidden_size

        transformed_hid_ = transformed_hid.dimshuffle(1, 0, 2)
        h_i = transformed_hid_[0]
        h_f = transformed_hid_[1]
        h_c = transformed_hid_[2]
        h_o = transformed_hid_[3]  # batch_size x hidden_size

        transformed_cell_ = transformed_cell.dimshuffle(1, 0, 2)
        c_i = transformed_cell_[0]
        c_f = transformed_cell_[1]  # batch_size x hidden_size

        in_lin = x_i + h_i + b_i + c_i
        forget_lin = x_f + h_f + b_f + c_f
        cell_lin = x_c + h_c + b_c

        in_gate = T.nnet.sigmoid(in_lin)
        forget_gate = T.nnet.sigmoid(forget_lin)
        cell_updates = T.tanh(cell_lin)
        in_gate.name = "in_gate"
        forget_gate.name = "forget_gate"
        cell_updates.name = "cell_updates"

        cell = forget_gate * prev_cell + in_gate * cell_updates

        out_lin = x_o + h_o + b_o + T.dot(cell, V_o)
        out_gate = T.nnet.sigmoid(out_lin)
        out_gate.name = "out_gate"

        hid = out_gate * T.tanh(cell)

        if mask is not None:
            mask = mask.dimshuffle(0, 'x')
            cell = T.switch(mask, cell, prev_cell)
            hid = T.switch(mask, hid, prev_hid)
        return cell, hid
    return _step
