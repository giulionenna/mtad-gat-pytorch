import os
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import mean_squared_error
import argparse

from utils import *
from mtad_gat import MTAD_GAT


def evaluate(model, loader, criterion):
	model.eval()

	losses = []
	with torch.no_grad():
		for x, y in loader:
			y_hat, recons = model(x)
			if y_hat.ndim == 3:
				y_hat = y_hat.squeeze(1)
			if y.ndim == 3:
				y = y.squeeze(1)

			# loss = criterion(y_hat, y)
			loss = criterion(y, y_hat)
			losses.append(loss.item())

	return np.sqrt(np.array(losses).mean())


def predict(model, loader, dataset='hpc', plot_name=''):
	model.eval()

	preds = []
	true_y = []
	with torch.no_grad():
		for x, y in loader:
			y_hat, recons = model(x)
			if y_hat.ndim == 3:
				y_hat = y_hat.squeeze(1)
			if y.ndim == 3:
				y = y.squeeze(1)
			preds.extend(y_hat.detach().cpu().numpy())
			true_y.extend(y.detach().cpu().numpy())

	preds = np.array(preds)[1500:1750]
	true_y = np.array(true_y)[1500:1750]

	rmse = np.sqrt(mean_squared_error(true_y, preds))

	# Plot preds and true
	for i in range(preds.shape[1]):
		plt.plot([j for j in range(len(preds))], preds[:, i].ravel(), label='Preds')
		plt.plot([j for j in range(len(true_y))], true_y[:, i].ravel(), label='True')
		plt.title(f'{plot_name} | Feature: {i}')
		plt.legend()
		plt.savefig(f'plots/{dataset}/{plot_name}_feature{i}.png', bbox_inches='tight')
		plt.show()
		plt.close()

	return rmse


if __name__ == '__main__':
	parser = argparse.ArgumentParser()

	# Data params
	parser.add_argument('--dataset', type=str, default='smd', choices=['hpc', 'gsd'],
						help='hpc: hourly household power consumption data /n gsd: gas sensor data')
	parser.add_argument('--lookback', type=int, default=100)
	parser.add_argument('--horizon', type=int, default=1)
	parser.add_argument('--target_col', type=int, default=None)

	# Model params
	parser.add_argument('--kernel_size', type=int, default=7)
	parser.add_argument('--gru_layers', type=int, default=1)
	parser.add_argument('--gru_hid_dim', type=int, default=8)
	parser.add_argument('--fc_layers', type=int, default=1)
	parser.add_argument('--fc_hid_dim', type=int, default=8)

	# Train params
	parser.add_argument('--test_size', type=float, default=0.2)
	parser.add_argument('--epochs', type=int, default=30)
	parser.add_argument('--bs', type=int, default=64)
	parser.add_argument('--lr', type=float, default=1e-4)
	parser.add_argument('--dropout', type=float, default=0.3)
	parser.add_argument('--use_cuda', type=bool, default=True)
	parser.add_argument('--model_path', type=str, default="./saved_models/")

	args = parser.parse_args()
	print(args)

	if not os.path.exists(f'plots/{args.dataset}'):
		os.makedirs(f'plots/{args.dataset}')

	#if not os.path.exists(f'ServerMachineDataset/processed'):
		#process_data()

	window_size = args.lookback
	horizon = args.horizon
	target_col = args.target_col
	n_epochs = args.epochs
	batch_size = args.bs

	(x_train, _), (x_test, y_test) = get_data('machine-1-1')

	cuda = torch.cuda.is_available() and args.use_cuda
	device = 'cuda' if cuda else 'cpu'

	x_train = torch.from_numpy(x_train).float().to(device)
	x_test = torch.from_numpy(x_test).float().to(device)

	x_dim = x_train.shape[1]

	train_dataset = SMDDataset(x_train, window=window_size)
	train_loader = DataLoader(train_dataset, shuffle=True, batch_size=batch_size, drop_last=True)

	test_dataset = SMDDataset(x_test, window=window_size)
	test_loader = DataLoader(test_dataset, shuffle=False, batch_size=batch_size, drop_last=True)

	model = MTAD_GAT(x_dim, window_size, horizon, x_dim,
					 kernel_size=args.kernel_size,
					 dropout=args.dropout,
					 gru_n_layers=args.gru_layers,
					 gru_hid_dim=args.gru_hid_dim,
					 forecasting_n_layers=args.fc_layers,
					 forecasting_hid_dim=args.fc_hid_dim,
					 device=device)

	print(f'Device: {device}')
	if cuda:
		model.cuda()

	optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
	criterion = nn.MSELoss()

	init_train_loss = evaluate(model, train_loader, criterion)
	print(f'Init train loss: {init_train_loss}')

	# init_val_loss = evaluate(model, val_loader, criterion)
	# print(f'Init val loss: {init_val_loss}')

	train_losses = []
	val_losses = []
	print(f'Training model for {n_epochs} epochs..')
	for epoch in range(n_epochs):
		model.train()
		batch_losses = []
		for x, y in train_loader:
			optimizer.zero_grad()
			preds, recons = model(x)
			if preds.ndim == 3:
				preds = preds.squeeze(1)
			if y.ndim == 3:
				y = y.squeeze(1)
			loss = torch.sqrt(criterion(y, preds))
			loss.backward()
			optimizer.step()

			batch_losses.append(loss.item())

		epoch_loss = np.array(batch_losses).mean()
		train_losses.append(epoch_loss)

		# Evaluate on validation set
		# val_loss = 0
		val_loss = evaluate(model, test_loader, criterion)
		val_losses.append(val_loss)

		print(f'[Epoch {epoch + 1}] Train loss: {epoch_loss:.5f}, Val loss: {val_loss:.5f}')

	plt.plot(train_losses, label='training loss')
	plt.plot(val_losses, label='validation loss')
	plt.xlabel("Epoch")
	plt.ylabel("MSE")
	plt.legend()
	plt.savefig(f'plots/{args.dataset}/losses.png', bbox_inches='tight')
	plt.show()
	plt.close()

	# Predict
	# Make train loader with no shuffle
	# train_loader = DataLoader(train_data, shuffle=False, batch_size=batch_size, drop_last=True)
	rmse_train = predict(model, train_loader, dataset=args.dataset, plot_name='train_preds')
	# rmse_val = predict(model, val_loader, scaler, target_col, dataset=args.dataset, plot_name='val_preds')
	rmse_test = predict(model, test_loader, dataset=args.dataset, plot_name='test_preds')

	print(rmse_test)

	test_loss = evaluate(model, test_loader, criterion)
	print(f'Test loss (RMSE): {test_loss:.3f}')









