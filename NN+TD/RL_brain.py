import numpy as np
import tensorflow as tf

np.random.seed(1)
tf.set_random_seed(1)


class DeepQNetwork:
    def __init__(
            self,
            n_actions,
            n_features,
            learning_rate=0.01,
            reward_decay=0.9,
            e_greedy=0.9,
            replace_target_iter=300,
            memory_size=500,
            batch_size=32,
            e_greedy_increment=0.01,
            output_graph=False,
    ):
        self.n_actions = n_actions  # 动作个数
        self.n_features = n_features
        self.lr = learning_rate
        self.gamma = reward_decay
        self.epsilon_max = e_greedy
        self.replace_target_iter = replace_target_iter
        self.memory_size = memory_size
        self.batch_size = batch_size
        self.epsilon_increment = e_greedy_increment
        self.epsilon = 0
        # self.epsilon = 0 if e_greedy_increment is not None else self.epsilon_max
        self.learn_step_counter = 0
        self.memory = np.zeros((self.memory_size, n_features * 2 + 3))
        self._build_net()

        t_params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='target_net')
        e_params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='eval_net')

        with tf.variable_scope('soft_replacement'):
            self.target_replace_op = [tf.assign(t, e) for t, e in zip(t_params, e_params)]

        self.sess = tf.Session()

        if output_graph:
            # $ tensorboard --logdir=logs
            tf.summary.FileWriter("logs/", self.sess.graph)

        self.sess.run(tf.global_variables_initializer())
        self.cost_his = []

    def _build_net(self):
        # ------------------ all inputs ------------------------
        self.s = tf.placeholder(tf.float32, [None, self.n_features], name='s')  # input State
        self.s_ = tf.placeholder(tf.float32, [None, self.n_features], name='s_')  # input Next State
        self.r = tf.placeholder(tf.float32, [None, ], name='r')  # input Reward
        self.a = tf.placeholder(tf.int32, [None, ], name='a')  # input Action
        self.g = tf.placeholder(tf.float32, [None, ], name='g')

        w_initializer, b_initializer = tf.random_normal_initializer(0., 0.3), tf.constant_initializer(0.1)

        # ------------------ build evaluate_net ------------------
        with tf.variable_scope('eval_net'):
            e1 = tf.layers.dense(self.s, 20, tf.nn.relu, kernel_initializer=w_initializer,
                                 bias_initializer=b_initializer, name='e1')
            self.q_eval = tf.layers.dense(e1, self.n_actions, kernel_initializer=w_initializer,
                                          bias_initializer=b_initializer, name='q')

        # ------------------ build target_net ------------------
        with tf.variable_scope('target_net'):
            t1 = tf.layers.dense(self.s_, 20, tf.nn.relu, kernel_initializer=w_initializer,
                                 bias_initializer=b_initializer, name='t1')
            self.q_next = tf.layers.dense(t1, self.n_actions, kernel_initializer=w_initializer,
                                          bias_initializer=b_initializer, name='t2')

        with tf.variable_scope('q_target'):
            # axis=1,每行的最大值
            # q_target = 0.8 * tf.reduce_max(self.q_next, axis=1, name='Qmax_s_') + \
                       #0.2 * (self.r - self.g + self.gamma * tf.reduce_max(self.q_next, axis=1, name='Qmax_s_'))
            q_target = (1 - self.gamma) * self.r + self.gamma * tf.reduce_max(self.q_next, axis=1, name='Qmax_s_')
            self.q_target = tf.stop_gradient(q_target)

        with tf.variable_scope('q_eval'):
            # tf.stack拼接矩阵,
            a_indices = tf.stack([tf.range(tf.shape(self.a)[0], dtype=tf.int32), self.a], axis=1)
            self.q_eval_wrt_a = tf.gather_nd(params=self.q_eval, indices=a_indices)    # shape=(None, )

        with tf.variable_scope('loss'):
            self.loss = tf.reduce_mean(tf.squared_difference(self.q_target, self.q_eval_wrt_a, name='TD_error'))
        with tf.variable_scope('train'):
            self._train_op = tf.train.RMSPropOptimizer(self.lr).minimize(self.loss)

    def store_transition(self, s, a, r, s_, g):
        if not hasattr(self, 'memory_counter'):
            self.memory_counter = 0
        transition = np.hstack((s, [a, r], s_, g))
        index = self.memory_counter % self.memory_size
        self.memory[index, :] = transition
        self.memory_counter += 1

    def choose_action(self, observation):
        # 统一 observation 的 shape (1, size_of_observation)
        observation = observation[np.newaxis, :]
        print('observation: ', observation)
        if np.random.uniform() < self.epsilon:
            # forward feed the observation and get q value for every actions,通过状态算出动作值
            actions_value = self.sess.run(self.q_eval, feed_dict={self.s: observation})
            action = np.argmax(actions_value)
            flag = 1
        else:
            action = np.random.randint(0, self.n_actions)
            flag = 0
        print("action={0}, flag={1}".format(action, flag))
        return action, flag

    def learn(self):
        if self.learn_step_counter % self.replace_target_iter == 0:
            self.sess.run(self.target_replace_op)
            print('\ntarget_params_replaced\n')

        # -------------------------从记忆库中提取记忆--------------------------
        # sample batch memory from all memory
        if self.memory_counter > self.memory_size:
            # memory_size=2000,batch_size=32，从2000中随机选择32个数当作采样索引
            sample_index = np.random.choice(self.memory_size, size=self.batch_size)
        else:
            sample_index = np.random.choice(self.memory_counter, size=self.batch_size)
        # 构成批记忆库
        batch_memory = self.memory[sample_index, :]

        # -------------------------用批记忆库训练神经网络-----------------------
        # 训练eval_net
        _, cost = self.sess.run(
            [self._train_op, self.loss],
            feed_dict={
                self.s: batch_memory[:, :self.n_features],  # 前n_features列的数据，表示方法很叼
                self.a: batch_memory[:, self.n_features],  # 第n_features列的数据
                self.r: batch_memory[:, self.n_features + 1],  # 第n_features+1列的数据
                self.s_: batch_memory[:, self.n_features + 2: self.n_features + 5],   # 最后n_features列的数据
                self.g: batch_memory[:, self.n_features + 5]
            })

        self.cost_his.append(cost)

        # 逐渐增加 epsilon, 降低行为的随机性
        self.epsilon = self.epsilon + self.epsilon_increment if self.epsilon < self.epsilon_max else self.epsilon_max
        self.learn_step_counter += 1
        print('epsilon:', self.epsilon)
        print('learning_step_counter:', self.learn_step_counter)

    def plot_cost(self):
        import matplotlib.pyplot as plt
        plt.plot(np.arange(len(self.cost_his)), self.cost_his)
        plt.ylabel('Cost')
        plt.xlabel('training steps')
        plt.show()


if __name__ == '__main__':
    DQN = DeepQNetwork(3, 4, output_graph=False)
