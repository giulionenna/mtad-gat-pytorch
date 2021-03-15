import numpy as np
from spot import SPOT


def adjust_predicts(score, label, threshold,
					advance=1,
					pred=None,
					calc_latency=False):
	"""
	Calculate adjusted predict labels using given `score`, `threshold` (or given `pred`) and `label`.
	Args:
		score (np.ndarray): The anomaly score
		label (np.ndarray): The ground-truth label
		threshold (float): The threshold of anomaly score.
			A point is labeled as "anomaly" if its score is lower than the threshold.
		pred (np.ndarray or None): if not None, adjust `pred` and ignore `score` and `threshold`,
		calc_latency (bool):
	Returns:
		np.ndarray: predict labels
	"""
	if len(score) != len(label):
		raise ValueError("score and label must have the same length")
	score = np.asarray(score)
	label = np.asarray(label)
	if pred is None:
		predict = score > threshold
	else:
		predict = pred

	actual = label > 0.1
	anomaly_state = False
	anomaly_count = 0
	latency = 0

	# Added advance in case model predicts anomaly 'in advance' within a small window
	# Advance should be 0 or small
	for i in range(len(score)):
		if any(actual[max(i-advance, 0):i+1]) and predict[i] and not anomaly_state:
			anomaly_state = True
			anomaly_count += 1
			for j in range(i, 0, -1):
				if not actual[j]:
					break
				else:
					if not predict[j]:
						predict[j] = True
						latency += 1
		elif not actual[i]:
			anomaly_state = False
		if anomaly_state:
			predict[i] = True
	if calc_latency:
		return predict, latency / (anomaly_count + 1e-4)
	else:
		return predict


def calc_point2point(predict, actual):
	"""
	calculate f1 score by predict and actual.
	Args:
		predict (np.ndarray): the predict label
		actual (np.ndarray): np.ndarray
	"""
	TP = np.sum(predict * actual)
	TN = np.sum((1 - predict) * (1 - actual))
	FP = np.sum(predict * (1 - actual))
	FN = np.sum((1 - predict) * actual)
	precision = TP / (TP + FP + 0.00001)
	recall = TP / (TP + FN + 0.00001)
	f1 = 2 * precision * recall / (precision + recall + 0.00001)
	return f1, precision, recall, TP, TN, FP, FN

	# Code from Time-Series Anomaly Detection Service at Microsof: https://arxiv.org/pdf/1906.03821.pdf
	# splits = np.where(label[1:] != label[:-1])[0] + 1
	# print(splits)
	# is_anomaly = label[0] == 1
	# new_predict = np.array(predict)
	# pos = 0
	#
	# for sp in splits:
	# 	if is_anomaly:
	# 		if 1 in predict[(pos - advance):min(pos + delay + 1, sp)]:
	# 			new_predict[pos: sp] = 1
	# 		else:
	# 			new_predict[pos: sp] = 0
	# 	is_anomaly = not is_anomaly
	# 	pos = sp
	# sp = len(label)
	#
	# if is_anomaly:  # anomaly in the end
	# 	if 1 in predict[(pos - advance): min(pos + delay + 1, sp)]:
	# 		new_predict[pos: sp] = 1
	# 	else:
	# 		new_predict[pos: sp] = 0
	#
	# return new_predict


def pot_eval(init_score, score, label, q=1e-3, level=0.99):
	"""
	Run POT method on given score.
	Args:
		init_score (np.ndarray): The data to get init threshold.
			For `OmniAnomaly`, it should be the anomaly score of train set.
		score (np.ndarray): The data to run POT method.
			For `OmniAnomaly`, it should be the anomaly score of test set.
		label:
		q (float): Detection level (risk)
		level (float): Probability associated with the initial threshold t
	Returns:
		dict: pot result dict
	"""
	print(f'Running POT with q={q}, level={level}..')
	s = SPOT(q)  # SPOT object
	s.fit(init_score, score)  # data import
	s.initialize(level=level, min_extrema=False)  # initialization step
	# ret = s.run(dynamic=True)  # run
	ret = s.run(dynamic=False, with_alarm=False)  # much faster
	print(len(ret['alarms']))
	print(len(ret['thresholds']))

	pot_th = np.mean(ret['thresholds'])
	pred, p_latency = adjust_predicts(score, label, pot_th, calc_latency=True)
	# pred = adjust_predicts(score, label, pot_th, advance=1, delay=30)
	p_t = calc_point2point(pred, label)
	print('POT result: ', p_t, pot_th)
	return {
		'pot-f1': p_t[0],
		'pot-precision': p_t[1],
		'pot-recall': p_t[2],
		'pot-TP': p_t[3],
		'pot-TN': p_t[4],
		'pot-FP': p_t[5],
		'pot-FN': p_t[6],
		'pot-threshold': pot_th,
		'pot-latency': p_latency,
		'pred': pred,
		'pot_thresholds': ret['thresholds']
	}


def bf_search(score, label, start, end=None, step_num=1, display_freq=1, verbose=True):
	"""
	Find the best-f1 score by searching best `threshold` in [`start`, `end`).
	Returns:
		list: list for results
		float: the `threshold` for best-f1
	"""
	if step_num is None or end is None:
		end = start
		step_num = 1
	search_step, search_range, search_lower_bound = step_num, end - start, start
	if verbose:
		print("search range: ", search_lower_bound, search_lower_bound + search_range)
	threshold = search_lower_bound
	m = (-1., -1., -1.)
	m_t = 0.0
	for i in range(search_step):
		threshold += search_range / float(search_step)
		target = calc_seq(score, label, threshold)
		if target[0] > m[0]:
			m_t = threshold
			m = target
		if verbose and i % display_freq == 0:
			print("cur thr: ", threshold, target, m, m_t)
	print(m, m_t)
	return m, m_t


def calc_seq(score, label, threshold):
	"""
	Calculate f1 score for a score sequence
	"""
	predict = adjust_predicts(score, label, threshold)
	return calc_point2point(predict, label)