import tensorflow as tf
from dis_model import DIS
from gen_model import GEN
import cPickle
import numpy as np
import utils as ut
import multiprocessing

cores = multiprocessing.cpu_count()

#########################################################################################
# Hyper-parameters
#########################################################################################
EMB_DIM = 5
DNS_K = 5
INIT_DELTA = 0.05
BATCH_SIZE = 16
workdir = 'ml-100k/'

DIS_TRAIN_FILE = workdir + 'dis-train.txt'
DIS_MODEL_FILE = workdir + "model_dns.pkl"
dataset_deliminator = None
user_index_original_dataset = 0
item_index_original_dataset = 1
rate_index_original_dataset = 2
#########################################################################################
# Load data
#########################################################################################
user_pos_train = {}
all_items_ids = []
all_user_ids = []
uid_to_index = {}
jid_to_index = {}

u_index = 0
j_index = 0
NUM_RATINGS_TRAIN = 0
with open(workdir + 'train')as fin:
    for line in fin:
        if dataset_deliminator == None:
            line = line.split()
        else:
            line = line.split(dataset_deliminator)
        if line[user_index_original_dataset] not in uid_to_index:
            uid_to_index[line[user_index_original_dataset]] = u_index
            u_index += 1
        if line[item_index_original_dataset] not in jid_to_index:
            jid_to_index[line[item_index_original_dataset]] = j_index
            j_index += 1
        uid = int(uid_to_index[line[user_index_original_dataset]])
        iid = int(jid_to_index[line[item_index_original_dataset]])
        #r = float(line[rate_index_original_dataset])
        r = 1
        if r > 0:
            if uid in user_pos_train:
                user_pos_train[uid].append(iid)
            else:
                user_pos_train[uid] = [iid]
        if iid not in all_items_ids:
            all_items_ids.append(iid)
        if uid not in all_user_ids:
            all_user_ids.append(uid)
        NUM_RATINGS_TRAIN += 1

user_pos_test = {}
NUM_RATINGS_TEST = 0
with open(workdir + 'test')as fin:
    for line in fin:
        if dataset_deliminator == None:
            line = line.split()
        else:
            line = line.split(dataset_deliminator)
        if line[user_index_original_dataset] not in uid_to_index:
            uid_to_index[line[user_index_original_dataset]] = u_index
            u_index += 1
        if line[item_index_original_dataset] not in jid_to_index:
            jid_to_index[line[item_index_original_dataset]] = j_index
            j_index += 1
        uid = int(uid_to_index[line[user_index_original_dataset]])
        iid = int(jid_to_index[line[item_index_original_dataset]])
        #r = float(line[rate_index_original_dataset])
        r = 1
        if r > 0:
            if uid in user_pos_test:
                user_pos_test[uid].append(iid)
            else:
                user_pos_test[uid] = [iid]
        if iid not in all_items_ids:
            all_items_ids.append(iid)
        if uid not in all_user_ids:
            all_user_ids.append(uid)
        NUM_RATINGS_TEST += 1

USER_NUM = len(all_user_ids)
ITEM_NUM = len(all_items_ids)
print(USER_NUM, ITEM_NUM)
all_items = set(range(ITEM_NUM))

all_users = user_pos_train.keys()
all_users.sort()


def dcg_at_k(r, k):
    r = np.asfarray(r)[:k]
    return np.sum(r / np.log2(np.arange(2, r.size + 2)))


def ndcg_at_k(r, k):
    dcg_max = dcg_at_k(sorted(r, reverse=True), k)
    if not dcg_max:
        return 0.
    return dcg_at_k(r, k) / dcg_max


def simple_test_one_user(x):
    rating = x[0]
    u = x[1]

    test_items = list(all_items - set(user_pos_train[u]))
    item_score = []
    for i in test_items:
        item_score.append((i, rating[i]))

    item_score = sorted(item_score, key=lambda x: x[1])
    item_score.reverse()
    item_sort = [x[0] for x in item_score]

    r = []
    for i in item_sort:
        if i in user_pos_test[u]:
            r.append(1)
        else:
            r.append(0)

    p_3 = np.mean(r[:3])
    p_5 = np.mean(r[:5])
    p_10 = np.mean(r[:10])
    ndcg_3 = ndcg_at_k(r, 3)
    ndcg_5 = ndcg_at_k(r, 5)
    ndcg_10 = ndcg_at_k(r, 10)

    return np.array([p_3, p_5, p_10, ndcg_3, ndcg_5, ndcg_10])


def simple_test(sess, model):
    result = np.array([0.] * 6)
    pool = multiprocessing.Pool(cores)
    batch_size = 128
    test_users = user_pos_test.keys()
    test_user_num = len(test_users)
    index = 0
    while True:
        if index >= test_user_num:
            break
        user_batch = test_users[index:index + batch_size]
        index += batch_size

        user_batch_rating = sess.run(model.all_rating, {model.u: user_batch})
        user_batch_rating_uid = zip(user_batch_rating, user_batch)
        batch_result = pool.map(simple_test_one_user, user_batch_rating_uid)
        for re in batch_result:
            result += re

    pool.close()
    ret = result / test_user_num
    ret = list(ret)
    return ret


def generate_for_d(sess, model, filename):
    data = []
    for u in user_pos_train:
        pos = user_pos_train[u]

        rating = sess.run(model.all_rating, {model.u: [u]})
        rating = np.array(rating[0]) / 0.2  # Temperature
        exp_rating = np.exp(rating)
        prob = exp_rating / np.sum(exp_rating)

        neg = np.random.choice(np.arange(ITEM_NUM), size=len(pos), p=prob)
        for i in range(len(pos)):
            data.append(str(u) + '\t' + str(pos[i]) + '\t' + str(neg[i]))

    with open(filename, 'w')as fout:
        fout.write('\n'.join(data))


def main():
    print "load model..."
    param = cPickle.load(open(workdir + "model_dns_ori.pkl"))
    param = None
    generator = GEN(ITEM_NUM, USER_NUM, EMB_DIM, lamda=0.0 / BATCH_SIZE, param=param, initdelta=INIT_DELTA,
                    learning_rate=0.001)
    discriminator = DIS(ITEM_NUM, USER_NUM, EMB_DIM, lamda=0.1 / BATCH_SIZE, param=None, initdelta=INIT_DELTA,
                        learning_rate=0.001)

    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    sess = tf.Session(config=config)
    sess.run(tf.global_variables_initializer())

    print "gen ", simple_test(sess, generator)
    print "dis ", simple_test(sess, discriminator)

    dis_log = open(workdir + 'dis_log.txt', 'w')
    gen_log = open(workdir + 'gen_log.txt', 'w')

    # minimax training
    best = 0.
    for epoch in range(15):
        if epoch >= 0:
            for d_epoch in range(100):
                if d_epoch % 5 == 0:
                    generate_for_d(sess, generator, DIS_TRAIN_FILE)
                    train_size = ut.file_len(DIS_TRAIN_FILE)
                index = 1
                while True:
                    if index > train_size:
                        break
                    if index + BATCH_SIZE <= train_size + 1:
                        input_user, input_item, input_label = ut.get_batch_data(DIS_TRAIN_FILE, index, BATCH_SIZE)
                    else:
                        input_user, input_item, input_label = ut.get_batch_data(DIS_TRAIN_FILE, index,
                                                                                train_size - index + 1)
                    index += BATCH_SIZE

                    _ = sess.run(discriminator.d_updates,
                                 feed_dict={discriminator.u: input_user, discriminator.i: input_item,
                                            discriminator.label: input_label})

            # Train G
            for g_epoch in range(50):  # 50
                for u in user_pos_train:
                    sample_lambda = 0.2
                    pos = user_pos_train[u]

                    rating = sess.run(generator.all_logits, {generator.u: u})
                    exp_rating = np.exp(rating)
                    prob = exp_rating / np.sum(exp_rating)  # prob is generator distribution p_\theta

                    pn = (1 - sample_lambda) * prob
                    pn[pos] += sample_lambda * 1.0 / len(pos)
                    # Now, pn is the Pn in importance sampling, prob is generator distribution p_\theta

                    sample = np.random.choice(np.arange(ITEM_NUM), 2 * len(pos), p=pn)
                    ###########################################################################
                    # Get reward and adapt it with importance sampling
                    ###########################################################################
                    reward = sess.run(discriminator.reward, {discriminator.u: u, discriminator.i: sample})
                    reward = reward * prob[sample] / pn[sample]
                    ###########################################################################
                    # Update G
                    ###########################################################################
                    _ = sess.run(generator.gan_updates,
                                 {generator.u: u, generator.i: sample, generator.reward: reward})

                result = simple_test(sess, generator)
                print "epoch ", epoch, "gen: ", result
                buf = '\t'.join([str(x) for x in result])
                gen_log.write(str(epoch) + '\t' + buf + '\n')
                gen_log.flush()

                p_5 = result[1]
                if p_5 > best:
                    print 'best: ', result
                    best = p_5
                    generator.save_model(sess, "ml-100k/gan_generator.pkl")

    gen_log.close()
    dis_log.close()


if __name__ == '__main__':
    main()