import tensorflow as tf
from dis_model import DIS
from gen_model import GEN
import pickle as cPickle
import numpy as np
import utils as ut
import multiprocessing
import matplotlib.pyplot as plt
from tqdm import tqdm
from mf_model import MF
from cf_dns import generate_uniform

cores = multiprocessing.cpu_count()

#########################################################################################
# Hyper-parameters
#########################################################################################
EMB_DIM = 5
DNS_K = 5
INIT_DELTA = 0.05
BATCH_SIZE = 16
TRAIN = False
workdir = 'ml-100k/'
DIS_TRAIN_FILE = workdir + 'dis-train.txt'
DIS_TRAIN_FILE_UNIFORM = workdir + 'dis-train-uniform.txt'
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
print("--->", USER_NUM, ITEM_NUM)
all_items = set(range(ITEM_NUM))

all_users = user_pos_train.keys()
sorted(all_users)


def dcg_at_k(r, k):
    r = np.asfarray(r)[:k]
    return np.sum(r / np.log2(np.arange(2, r.size + 2)))


def ndcg_at_k(r, k):
    dcg_max = dcg_at_k(sorted(r, reverse=True), k)
    if not dcg_max:
        return 0.
    return dcg_at_k(r, k) / dcg_max


def simple_test_one_user_test(x):
    rating = x[0]
    u = x[1]

    test_items = list(all_items - set(user_pos_train[u]))
    item_score = []
    for i in test_items:
        item_score.append((i, rating[i]))

    item_score = sorted(item_score, key=lambda x: x[1], reverse=True)
    item_sort = [(x[0], x[1]) for x in item_score]

    r = []
    rmse = 0
    for i, j in item_sort:
        if i in user_pos_test[u]:
            r.append(1)
            rmse += np.square(1-j)
        else:
            r.append(0)

    p_3 = np.mean(r[:3])
    p_5 = np.mean(r[:5])
    p_100 = np.mean(r[:100])

    ndcg_3 = ndcg_at_k(r, 3)
    ndcg_5 = ndcg_at_k(r, 5)
    ndcg_100 = ndcg_at_k(r, 100)

    return np.array([p_3, p_5, p_100, ndcg_3, ndcg_5, ndcg_100, rmse])

def simple_test_one_user_train(x):
    rating = x[0]
    u = x[1]

    test_items = list(all_items)
    item_score = []
    for i in test_items:
        item_score.append((i, rating[i]))

    item_score = sorted(item_score, key=lambda x: x[1], reverse=True)
    item_sort = [(x[0], x[1]) for x in item_score]

    r = []
    rmse = 0
    for i, j in item_sort:
        if i in user_pos_train[u]:
            r.append(1)
            rmse += np.square(1-j)
        else:
            r.append(0)

    p_3 = np.mean(r[:3])
    p_5 = np.mean(r[:5])
    p_100 = np.mean(r[:100])

    ndcg_3 = ndcg_at_k(r, 3)
    ndcg_5 = ndcg_at_k(r, 5)
    ndcg_100 = ndcg_at_k(r, 100)

    return np.array([p_3, p_5, p_100, ndcg_3, ndcg_5, ndcg_100, rmse])

def evaluate(sess, model, which_set = "test"):
    num_ratings = 0
    if which_set == "test":
        which_func = simple_test_one_user_test
        num_ratings = NUM_RATINGS_TEST
    else:
        which_func = simple_test_one_user_train
        num_ratings = NUM_RATINGS_TRAIN
    result = np.array([0.] * 3)
    pool = multiprocessing.Pool(cores)
    batch_size = 128
    test_users = list(user_pos_test.keys())
    test_user_num = len(test_users)
    index = 0
    while True:
        if index >= test_user_num:
            break
        user_batch = test_users[index:index + batch_size]
        index += batch_size

        user_batch_rating = sess.run(model.all_rating, {model.u: user_batch})
        user_batch_rating_uid = list(zip(user_batch_rating, user_batch))
        batch_result = pool.map(which_func, user_batch_rating_uid)
        for re in batch_result:
            result += [re[1], re[4], re[6]]
    pool.close()
    ret = (np.array(result.tolist()[:2]) / test_user_num).tolist()
    ret.append((np.array(result.tolist()[2]) / num_ratings).tolist())
    ret = list(zip(["p_5", "ndcg_5", "rmse"], ret))
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
    print("load model...")
    #param = cPickle.load(open(workdir + "model_dns_ori.pkl"))
    param = None
    generator = GEN(ITEM_NUM, USER_NUM, EMB_DIM, lamda=0.0 / BATCH_SIZE, param=param, initdelta=INIT_DELTA,
                    learning_rate=0.001)
    discriminator = DIS(ITEM_NUM, USER_NUM, EMB_DIM, lamda=0.1 / BATCH_SIZE, param=None, initdelta=INIT_DELTA,
                        learning_rate=0.001)
    mf = MF(ITEM_NUM, USER_NUM, EMB_DIM, lamda=0.1, param=param, initdelta=0.05, learning_rate=0.05)
    generate_uniform(DIS_TRAIN_FILE_UNIFORM) # Uniformly sample negative examples

    config = tf.compat.v1.ConfigProto()
    config.gpu_options.allow_growth = True
    sess = tf.compat.v1.Session(config=config)
    sess.run(tf.compat.v1.global_variables_initializer())

    result_train_gen = evaluate(sess, generator, "train")
    result_test_gen = evaluate(sess, generator, "test")
    result_train_dis = evaluate(sess, discriminator, "train")
    result_test_dis = evaluate(sess, discriminator, "test")
    result_train_mf = evaluate(sess, mf, "train")
    result_test_mf = evaluate(sess, mf, "test")

    print("epoch GEN", "0" , "gen train: ", result_train_gen, "gen test:", result_test_gen)
    print("epoch DIS", "0", "dis train: ", result_train_dis, "dis test:", result_test_dis)
    print("epoch MF", "0", "mf train: ", result_train_mf, "mf test:", result_test_mf)

    # creating initial data values
    # of x and y
    x_values = np.array([0])
    y_values_train_gen =  np.array([result_train_gen[0][1]])
    y_values_test_gen =  np.array([result_test_gen[0][1]])
    y_values_train_dis =  np.array([result_train_dis[0][1]])
    y_values_test_dis =  np.array([result_test_dis[0][1]])
    y_values_train_mf =  np.array([result_train_mf[0][1]])
    y_values_test_mf =  np.array([result_test_mf[0][1]])

    best_train_gen = result_train_gen
    best_test_gen = result_test_gen
    best_train_dis = result_train_dis
    best_test_dis = result_test_dis

    num_iterations = 30
    num_iterations_dis = 10
    num_iterations_gen = 10
    # minimax training
    for epoch in range(num_iterations):
        for d_epoch in tqdm(range(num_iterations_dis)):
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
            result_train_dis = evaluate(sess, discriminator, "train")
            result_test_dis = evaluate(sess, discriminator, "test")
            if result_train_dis[1] > best_train_dis[1]:
                best_train_dis = result_train_dis
                best_test_dis = result_test_dis
                discriminator.save_model(sess, workdir + "gan_discriminator.pkl")

        # Train G
        for g_epoch in tqdm(range(num_iterations_gen)):  # 50
            for u in user_pos_train:
                sample_lambda = 0.2
                pos = user_pos_train[u]

                rating = sess.run(generator.all_logits, {generator.u: u})
                exp_rating = np.exp(rating)
                prob = exp_rating / np.sum(exp_rating)  # prob is generator distribution p_\theta

                pn = (1 - sample_lambda) * prob
                pn[pos] += sample_lambda * 1.0 / len(pos)
                pn = np.divide(pn, np.sum(pn))
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
            result_train_gen = evaluate(sess, generator, "train")
            result_test_gen = evaluate(sess, generator, "test")
            if result_train_gen[1] > best_train_gen[1]:
                best_train_gen = result_train_gen
                best_test_gen = result_test_gen
                generator.save_model(sess, workdir + "gan_generator.pkl")

        with open(DIS_TRAIN_FILE_UNIFORM) as fmf:
            for line in fmf:
                line = line.split()
                u = int(line[0])
                i = int(line[1])
                j = int(line[2])
                #positive:
                _ = sess.run(mf.d_updates,
                             feed_dict={mf.u: [u], mf.pos: [i], mf.real: [1.0]})
                _ = sess.run(mf.d_updates,
                             feed_dict={mf.u: [u], mf.pos: [j], mf.real: [0.0]})

        result_train_mf = evaluate(sess, mf, "train")
        result_test_mf = evaluate(sess, mf, "test")

        print("epoch GEN", epoch, "gen train: ", result_train_gen, "gen test:", result_test_gen)
        print("epoch DIS", epoch, "dis train: ", result_train_dis, "dis test:", result_test_dis)
        print("epoch MF", epoch, "mf train: ", result_train_mf, "mf test:", result_test_mf)

        x_values = np.append(x_values, epoch)

        y_values_train_gen = np.append(y_values_train_gen, result_train_gen[0][1])
        y_values_test_gen = np.append(y_values_test_gen, result_test_gen[0][1])
        y_values_train_dis = np.append(y_values_train_dis, result_train_dis[0][1])
        y_values_test_dis = np.append(y_values_test_dis, result_test_dis[0][1])
        y_values_train_mf = np.append(y_values_train_mf, result_train_mf[0][1])
        y_values_test_mf = np.append(y_values_test_mf, result_test_mf[0][1])

    if TRAIN:
        line1, = plt.plot(x_values, y_values_train_gen, label = "P@5 Train GEN")
        line1.set_xdata(x_values)
        line1.set_ydata(y_values_train_gen)
        line2, = plt.plot(x_values, y_values_train_dis, label = "P@5 Train DIS")
        line2.set_xdata(x_values)
        line2.set_ydata(y_values_train_dis)
        line3, = plt.plot(x_values, y_values_train_mf, label = "P@5 Train MF")
        line3.set_xdata(x_values)
        line3.set_ydata(y_values_train_mf)

    line4, = plt.plot(x_values, y_values_test_gen, label = "P@5 Test GEN")
    line4.set_xdata(x_values)
    line4.set_ydata(y_values_test_gen)
    line5, = plt.plot(x_values, y_values_test_dis, label = "P@5 Test DIS")
    line5.set_xdata(x_values)
    line5.set_ydata(y_values_test_dis)
    line6, = plt.plot(x_values, y_values_test_mf, label = "P@5 Test MF")
    line6.set_xdata(x_values)
    line6.set_ydata(y_values_test_mf)


    plt.title("Model convergence", fontsize=20)

    plt.xlabel("Iteration")
    plt.ylabel("Model Performance")
    plt.legend()
    plt.show()


if __name__ == '__main__':
    main()
