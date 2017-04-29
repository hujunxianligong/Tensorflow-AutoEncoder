#coding = utf-8
import tensorflow as tf
import numpy as np

class DataIterator(object):
    def __init__(self, datas, labels = None, batch_size = 60, dtype = np.float64):
        if type(datas) == list:
            datas = np.array(datas, dtype = dtype)
        if labels != None:
            if type(labels) == list:
                labels = np.array(labels)
            labels = labels.astype(np.int32)

        self.data_count = len(datas)
        if labels !=None and len(labels.shape) == 1:
            self.class_num = labels.max() + 1
            label_matrix = np.zeros((self.data_count, self.class_num))
            label_matrix[range(self.data_count), labels] = 1
            labels = label_matrix

        self.batch_size = batch_size
        self.datas = datas
        self.batch_count = (self.data_count - 1)/batch_size + 1
        self.labels = labels
        self.reset()

    def reset(self):
        self.next_batch_index = 0

    def has_next(self):
        return self.next_batch_index < self.batch_count

    def next(self):
        if not self.has_next():
            return None
        next_data_batch = self.datas[self.next_batch_index::self.batch_count]
        if self.labels == None:
            result = [next_data_batch, None]
        else:
            next_label_batch = self.labels[self.next_batch_index::self.batch_count]
            result = [next_data_batch, next_label_batch]
        self.next_batch_index += 1
        return result



def default_cost_listener(epoch, batch_index, cost_value):
    if epoch % 20 ==0 and batch_index % 10 == 0:
        print "epoch: {} batch: {} cost: {}".format(epoch, batch_index, cost_value)


class AutoEncoder(object):

    def __init__(self, cost_listener = default_cost_listener):
        self.cost_listener = cost_listener

    def fine_tune(self,
                ite,
                learning_rate = 0.01,
                max_epoch = 1000,
                supervised = False,
                keep_prob = 1.0
                ):
        if supervised:
            self.supervised_fine_tune(ite, learning_rate, max_epoch, keep_prob)
        else:
            self.unsupervised_fine_tune(ite, learning_rate, max_epoch, keep_prob)

    def unsupervised_fine_tune(self, ite, learning_rate, max_epoch, keep_prob):
        print "\nstart unsupervised fine tuning ============\n"
        self.sess.close()
        self.init_tf_vars(reuse = True)
        self.build_base_structure(keep_prob)
        self.optimize_cost(ite, learning_rate, max_epoch, keep_prob)
        self.save_unstacked_params()

    def supervised_fine_tune(self, ite, learning_rate, max_epoch, keep_prob):
        print "\nstart supervised fine tuning ============\n"

        self.sess.close()
        self.init_tf_vars(reuse = True)
        self.build_base_structure(keep_prob)

        ite.reset()
        peek_batch = ite.next()
        class_num = peek_batch[1].shape[1]
        ite.reset()

        self.fine_tune_outputs = self.build_fine_tuning(class_num)
        fine_tune_outputs_holder = tf.placeholder(tf.float32, [None, class_num])
        fine_tune_cost = tf.reduce_mean(-tf.reduce_sum(fine_tune_outputs_holder * tf.log(tf.clip_by_value(self.fine_tune_outputs, 1e-10, 1.0)), reduction_indices=1))
        fine_tune_optimizer = tf.train.AdamOptimizer(learning_rate = learning_rate).minimize(fine_tune_cost)

        self.init_session()

        for epoch in range(max_epoch):
            ite.reset()
            while ite.has_next():
                batch_index = ite.next_batch_index
                batch_inputs, batch_labels = ite.next()

                feed_dict = {
                        self.inputs_holder: batch_inputs,
                        fine_tune_outputs_holder: batch_labels,
                        self.keep_prob: keep_prob
                        }
                _, c = self.sess.run([fine_tune_optimizer, fine_tune_cost], feed_dict = feed_dict)
                self.cost_listener(epoch, batch_index, c)

        self.save_unstacked_params()

    # neuron_nums is the number of neuron for each hidden layer
    # the number of neuron of input layer and decoder is excluded
    def fit(self,
            neuron_nums,
            ite,
            learning_rate = 0.01,
            max_epoch = 1000,
            stacked = False,
            hidden_activation = "tanh",
            keep_prob = 1.0
            ):
        #self.stacked = stacked
        self.hidden_activation = hidden_activation
        if stacked:
            self.stacked_fit(neuron_nums, ite, learning_rate, max_epoch, keep_prob)
        else:
            self.unstacked_fit(neuron_nums, ite, learning_rate, max_epoch, keep_prob)

    def stacked_fit(self, neuron_nums, ite, learning_rate, max_epoch, keep_prob):
        self.hidden_activation = "sigmoid"
        self.ws = neuron_nums

        ite.reset()
        peek_batch = ite.next()
        self.input_dim = peek_batch[0].shape[1]
        ite.reset()

        self.ws = [self.input_dim] + self.ws

        autoencoders = []

        current_ite = ite
        #train each layer greedily
        for i in range(1, len(self.ws)):
            print "\ntraining layer {}\n".format(i)
            current_autoencoder = AutoEncoder(cost_listener = self.cost_listener)
            if type(max_epoch) == list:
                current_max_epoch = max_epoch[i - 1]
            else:
                current_max_epoch = max_epoch
            current_autoencoder.fit([self.ws[i]], current_ite, hidden_activation = "sigmoid",
                    learning_rate = learning_rate, max_epoch = current_max_epoch, keep_prob = keep_prob)
            current_outputs = None

            current_ite.reset()
            while current_ite.has_next():
                #batch_index = ite.next_batch_index
                batch_inputs, _ = current_ite.next()
                batch_outputs = current_autoencoder.encode(batch_inputs)
                if current_outputs == None:
                    current_outputs = batch_outputs
                else:
                    current_outputs = np.concatenate((current_outputs, batch_outputs), 0)
            print "************"
            print current_outputs
            current_ite = DataIterator(current_outputs)
            current_autoencoder.close()
            autoencoders.append(current_autoencoder)
        self.save_stacked_params(autoencoders)

        self.init_tf_vars(reuse = True)
        self.build_base_structure(keep_prob)
        self.init_session()

    def init_session(self):
        self.sess = tf.Session()
        self.sess.run(tf.initialize_all_variables())


    def build_base_structure(self, keep_prob):
        self.inputs_holder = tf.placeholder(tf.float32, [None, self.ws[0]])
        self.keep_prob = tf.placeholder(tf.float32)
        if keep_prob == 1.0:
            use_dropout = False
        else:
            use_dropout = True
        if use_dropout:
            self.noisy_inputs = tf.nn.dropout(self.inputs_holder, self.keep_prob)
            self.encoder = self.build_encoder(self.noisy_inputs)
        else:
            self.encoder = self.build_encoder(self.inputs_holder)
        self.generator_inputs_holder = tf.placeholder(tf.float32, [None, self.ws[-1]])
        self.generator = self.build_decoder(self.generator_inputs_holder)
        self.decoder = self.build_decoder(self.encoder)

    # def corrupt_inputs(self, inputs, corrupt):
        # noise_mask = np.random.rand(inputs.shape[0], inputs.shape[1]) - 0.5
        # noise_mask[noise_mask > corrupt / 2] = 0
        # noise_mask[noise_mask < -corrupt / 2] = 0
        # return inputs + noise_mask

    def optimize_cost(self, ite, learning_rate, max_epoch, keep_prob):
        cost = tf.reduce_mean(tf.pow(self.decoder - self.inputs_holder, 2))
        optimizer = tf.train.AdamOptimizer(learning_rate = learning_rate).minimize(cost)
        self.init_session()
        for epoch in range(max_epoch):
            ite.reset()
            while ite.has_next():
                batch_index = ite.next_batch_index
                batch_inputs, _ = ite.next()

                feed_dict = {
                    self.inputs_holder: batch_inputs,
                    self.keep_prob: keep_prob
                    }
                _, c = self.sess.run([optimizer, cost], feed_dict = feed_dict)
                self.cost_listener(epoch, batch_index, c)

    def unstacked_fit(self, neuron_nums, ite, learning_rate, max_epoch, keep_prob):
        self.ws = neuron_nums
        ite.reset()
        peek_batch = ite.next()
        self.input_dim = peek_batch[0].shape[1]
        ite.reset()
        self.ws = [self.input_dim] + self.ws
        self.init_tf_vars()

        self.build_base_structure(keep_prob)
        print "\nstart training autoencoder ============\n"
        self.optimize_cost(ite, learning_rate, max_epoch, keep_prob)
        self.save_unstacked_params()

    def save_stacked_params(self, autoencoders):
        self.params = {"encoder": [], "decoder": []}
        for autoencoder in autoencoders:
            self.params["encoder"].append(autoencoder.params["encoder"][0])
            self.params["decoder"].append(autoencoder.params["decoder"][-1])
        self.params["decoder"].reverse()

    def save_unstacked_params(self):
        self.params = {"encoder": [], "decoder": []}
        for encoder_var in self.tf_vars["encoder"]:
            W = self.sess.run(encoder_var["W"])
            b = self.sess.run(encoder_var["b"])
            self.params["encoder"].append({"W": W, "b": b})
        for decoder_var in self.tf_vars["decoder"]:
            W = self.sess.run(decoder_var["W"])
            b = self.sess.run(decoder_var["b"])
            self.params["decoder"].append({"W": W, "b": b})

    def init_tf_vars(self, reuse = False):
        self.tf_vars = {}
        self.tf_vars["encoder"] = []
        self.tf_vars["decoder"] = []

        for i in range(len(self.ws) - 1):
            if not reuse:
                W = tf.Variable(tf.truncated_normal([self.ws[i], self.ws[i + 1]]))
                b = tf.Variable(tf.truncated_normal([self.ws[i + 1]]))
            else:
                param = self.params["encoder"][i]
                W = tf.Variable(param["W"])
                b = tf.Variable(param["b"])
            self.tf_vars["encoder"].append({"W": W, "b": b})

        for i in range(1, len(self.ws)):
            if not reuse:
                W = tf.Variable(tf.truncated_normal([self.ws[-i], self.ws[-(i+1)]]))
                b = tf.Variable(tf.truncated_normal([self.ws[-(i+1)]]))
            else:
                param = self.params["decoder"][i - 1]
                W = tf.Variable(param["W"])
                b = tf.Variable(param["b"])
            self.tf_vars["decoder"].append({"W": W, "b": b})


    def build_encoder(self, inputs):
        encoder = inputs
        for i, param_var in enumerate(self.tf_vars["encoder"]):
            W = param_var["W"]
            b = param_var["b"]
            encoder = tf.matmul(encoder, W) + b
            if self.hidden_activation == "sigmoid":
                encoder = tf.nn.sigmoid(encoder)
            elif self.hidden_activation == "tanh":
                encoder = tf.nn.tanh(encoder)
            else:
                raise Exception('Invalid Activation Function "{}"'.format(self.hidden_activation))
        return encoder

    def build_decoder(self, inputs):
        decoder = inputs
        for i, param_var in enumerate(self.tf_vars["decoder"]):
            W = param_var["W"]
            b = param_var["b"]
            decoder = tf.matmul(decoder, W) + b
            if i < len(self.tf_vars["decoder"]) - 1:
                if self.hidden_activation == "sigmoid":
                    decoder = tf.nn.sigmoid(decoder)
                else:
                    decoder = tf.nn.tanh(decoder)
            else:
                decoder = tf.nn.sigmoid(decoder)
        return decoder




    def encode(self, inputs):
        feed_dict = {self.inputs_holder: inputs, self.keep_prob: 1.0}
        encoder_outputs = self.sess.run(self.encoder, feed_dict = feed_dict)
        return encoder_outputs


    def decode(self, inputs):
        feed_dict = {self.generator_inputs_holder: inputs}
        decoder_outputs = self.sess.run(self.generator, feed_dict = feed_dict)
        return decoder_outputs

    def predict(self, inputs):
        feed_dict = {self.inputs_holder: inputs, self.keep_prob: 1.0}
        predicted_outputs = self.sess.run(self.fine_tune_outputs, feed_dict = feed_dict)
        return predicted_outputs

    def reconstruct(self, inputs):
        feed_dict = {self.inputs_holder: inputs, self.keep_prob: 1.0}
        reconstruct_outputs = self.sess.run(self.decoder, feed_dict = feed_dict)
        return reconstruct_outputs

    def build_fine_tuning(self, class_num):
        self.tf_vars["output"] = {}
        W = tf.Variable(tf.truncated_normal([self.ws[-1], class_num]), name="W")
        b = tf.Variable(tf.truncated_normal([class_num]))
        self.tf_vars["output"]["W"] = W
        self.tf_vars["output"]["b"] = b
        fine_tune_outputs = tf.matmul(self.encoder, W) + b
        fine_tune_outputs = tf.nn.softmax(fine_tune_outputs)
        return fine_tune_outputs


    def close(self):
        self.sess.close()
