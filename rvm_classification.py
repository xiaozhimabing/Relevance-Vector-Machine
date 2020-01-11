import random

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from tqdm import tqdm as tqdm

import Kernel


class RVM_Classifier:

    def __init__(self):

        # Alphas pruning threshold.
        self.threshold_alpha = 1e9

        # True if bias was pruned.
        self.removed_bias = False

        # Prior variances (weights).
        self.alphas = None
        self.alphas_old = None
        self.phi = None
        self.weight = None
        self.relevance_vector = None

        # Training and test data
        self.training_data = None
        self.training_labels = None
        self.test_data = None
        self.test_labels = None

        # Prediction
        self.prediction = None

    def set_training_data(self, training_data, training_labels):
        self.training_data = training_data
        self.training_labels = training_labels
        self.training_labels[self.training_labels == -1] = 0  # Sanitize labels, some use -1 and some use 0

    def set_predefined_training_data(self, data_set, data_set_index=1, nr_samples=None):
        self.training_data = np.loadtxt(
            "datasets/{data_set}/{data_set}_train_data_{index}.asc".format(data_set=data_set, index=data_set_index))
        self.training_labels = np.loadtxt(
            "datasets/{data_set}/{data_set}_train_labels_{index}.asc".format(data_set=data_set, index=data_set_index))
        self.training_labels[self.training_labels == -1] = 0  # Sanitize labels, some use -1 and some use 0

        self.test_data = np.loadtxt(
            "datasets/{data_set}/{data_set}_test_data_{index}.asc".format(data_set=data_set, index=data_set_index))
        self.test_labels = np.loadtxt(
            "datasets/{data_set}/{data_set}_test_labels_{index}.asc".format(data_set=data_set, index=data_set_index))
        self.test_labels[self.test_labels == -1] = 0  # Sanitize labels, some use -1 and some use 0

        if nr_samples is not None:
            random__training_data, random_training_target = self.get_nr_random_samples(self.training_data,
                                                                                       self.training_labels, nr_samples)
            self.training_data = random__training_data
            self.training_labels = random_training_target

            random__test_data, random_test_target = self.get_nr_random_samples(self.test_data, self.test_labels,
                                                                               nr_samples)
            self.test_data = random__test_data
            self.test_labels = random_test_target

    def get_nr_random_samples(self, data, target, nr_samples):
        total_nr_samples = data.shape[0]
        rnd_indexes = random.sample(range(total_nr_samples), nr_samples)

        random_data = []
        random_target = []
        for index in rnd_indexes:
            random_data.append(data[index])
            random_target.append(target[index])

        random_data = np.array(random_data)
        random_target = np.array(random_target)
        return random_data, random_target

    # From formula 16
    def recalculate_alphas_function(self, gamma, weights):
        return gamma / (weights ** 2)

    # From formula after 16 before 18 (17)
    def gamma_function(self, alpha, sigma):
        return 1 - alpha * np.diag(sigma)

    # Formula 26
    def sigma_function(self, phi, beta, alpha):
        b = np.linalg.multi_dot([phi.T, beta, phi])
        return np.linalg.inv(b + np.diag(alpha))

    # From under formula 25
    def beta_matrix_function(self, y, N):
        beta_matrix = np.zeros((N, N))
        for n in range(N):
            beta_matrix[n][n] = y[n] * (1 - y[n])
        return beta_matrix

    def phi_function(self, x, y, add=False):
        if add:
            phi_kernel = Kernel.radial_basis_kernel(x, y, 0.5)
            phi0 = np.ones((phi_kernel.shape[0], 1))
            return np.hstack((phi0, phi_kernel))
        return Kernel.radial_basis_kernel(x, y, 0.5)

    # Formula 2
    def y_function(self, weight, phi):
        y = expit(np.dot(phi, weight))  # Sigmoid function
        return y

    def log_posterior_function(self, weight, alpha, phi, target):
        y = self.y_function(weight, phi)

        y_1 = y[target == 1]
        t_1 = np.sum(np.log(y_1))
        y_0 = y[target == 0]
        t_0 = np.sum(np.log(1 - y_0))

        # Todo Optimize this, super slow
        # t_1 = 0
        # t_0 = 0
        # for n in range(len(target)):
        #     if target[n] == 1:
        #         t_1 += np.log(y[n])
        #     else:
        #         t_0 += np.log(1-y[n])
        log_posterior = t_1 + t_0 - np.linalg.multi_dot([weight.T, np.diag(alpha), weight]) / 2
        jacobian = np.dot(np.diag(alpha), weight) - np.dot(phi.T, (target - y))
        return -log_posterior, jacobian

    def hessian(self, mu_posterior, alphas, phi, T):
        y = self.y_function(mu_posterior, phi)
        B = np.diag(y * (1 - y))
        return np.diag(alphas) + np.dot(phi.T, np.dot(B, phi))

    def update_weights(self):
        result = minimize(
            fun=self.log_posterior_function,
            hess=self.hessian,
            x0=self.weight,
            args=(self.alphas, self.phi, self.training_labels),
            method='Newton-CG',
            jac=True,
            options={
                'maxiter': 50
            }
        )
        self.weight = result.x  # Updates the weights to the maximized (log is negative that is why we minimize)
        sigma_posterior = np.linalg.inv(self.hessian(self.weight, self.alphas, self.phi, self.training_labels))
        return sigma_posterior

    def sigma_posterior_function(self):
        sigma_posterior = np.linalg.inv(self.hessian(self.weight, self.alphas, self.phi, self.training_labels))
        return sigma_posterior

    # This function needs to be changed
    def prune(self):
        """
            Pruning based on alpha values.
        """
        mask = self.alphas < self.threshold_alpha

        self.alphas = self.alphas[mask]
        self.alphas_old = self.alphas_old[mask]
        self.phi = self.phi[:, mask]
        self.weight = self.weight[mask]

        if not self.removed_bias:
            self.relevance_vector = self.relevance_vector[mask[1:]]
        else:
            self.relevance_vector = self.relevance_vector[mask]

        if not mask[0] and not self.removed_bias:
            self.removed_bias = True
            print("Bias removed")

    def fit(self):
        """
            Train the classifier
        """
        self.relevance_vector = self.training_data
        self.phi = self.phi_function(self.training_data, self.training_data, True)

        # Initialize uniformly
        self.alphas = np.array([1 / (self.training_data.shape[0] + 1)] * (self.training_data.shape[0] + 1))
        self.weight = np.array([1 / (self.training_data.shape[0] + 1)] * (self.training_data.shape[0] + 1))

        max_training_iterations = 10000
        threshold = 1e-3
        for i in tqdm(range(max_training_iterations)):
            self.alphas_old = np.copy(self.alphas)

            sigma_posterior = self.update_weights()
            # sigma_posterior = self.sigma_posterior_function()  # Todo explore sigma_posterior bug

            y = self.y_function(self.weight, self.phi)
            beta = self.beta_matrix_function(y, self.training_data.shape[0])
            sigma = self.sigma_function(self.phi, beta, self.alphas)

            gammas = self.gamma_function(self.alphas, sigma)
            self.alphas = self.recalculate_alphas_function(gammas, self.weight)

            self.prune()

            difference = np.amax(np.abs(self.alphas - self.alphas_old))  # Need to change this
            if difference < threshold:
                print("Training done, it converged. Nr iterations: " + str(i + 1))
                break

    def predict(self, data=[], use_predifined_training=False):
        if data == []:
            if use_predifined_training:
                data = self.training_data
            else:
                data = self.test_data

        phi = self.phi_function(data, self.relevance_vector, True)
        # Don't know what this means
        # if not self.removed_bias:
        #     bias_trick = np.ones((X.shape[0], 1))
        #     phi = np.hstack((bias_trick, phi))

        y = self.y_function(self.weight, phi)
        pred = np.where(y > 0.5, 1, 0)
        self.prediction = pred
        return pred

    def plot(self, data=[], target=[]):
        if data == [] and target == []:
            data = self.test_data
            target = self.test_labels
        else:
            target[target == -1] = 0  # Sanitize labels, some use -1 and some use 0

        # Format data so we can plot it
        print("Will start plotting")
        target_values = np.unique(target)
        data_index_target_list = [0] * len(target_values)
        for i, c in enumerate(target_values):  # Saving the data index with its corresponding target
            data_index_target_list[i] = (c, np.argwhere(target == c))

        h = 0.01  # step size in the mesh
        # create a mesh to plot in
        x_min, x_max = data[:, 0].min(), data[:, 0].max()  # Gets the max and min value of x in the data
        y_min, y_max = data[:, 1].min(), data[:, 1].max()  # Gets the max and min value of y in the data
        xx, yy = np.meshgrid(np.arange(x_min, x_max, h),
                             np.arange(y_min, y_max, h))  # Creates a mesh from max and min with step size h

        # Plot the decision boundary. For that, we will assign a color to each
        # point in the mesh [x_min, m_max]x[y_min, y_max].
        print("Calculating the prediction, this might take a while...")
        data_mesh = np.c_[xx.ravel(), yy.ravel()]
        Z = self.predict(data_mesh)

        # Put the result into a color plot
        Z = Z.reshape(xx.shape)

        colors = ["bx", "go", "ro", "co", "mo", "yo", "bo", "wo"]
        plt.figure(figsize=(12, 6))
        plt.title('Banana dataset')
        plt.contour(xx, yy, Z, cmap=plt.cm.Paired)
        for i, c in enumerate(data_index_target_list):
            plt.plot(data[c[1], 0], data[c[1], 1], colors[i], label="Target: " + str(c[0]))
        plt.scatter(self.relevance_vector[:, 0], self.relevance_vector[:, 1], c='black', marker='+', s=500)
        plt.xlabel("Cool label, what should we put here")
        plt.ylabel("Heelloooo lets goo")
        plt.legend()
        plt.show()

    def get_prediction_error_rate(self, predicted_targets=[], true_targets=[], use_predefined_training=False):
        if predicted_targets == [] and true_targets == []:
            predicted_targets = self.prediction
            if use_predefined_training:
                true_targets = self.training_labels
            else:
                true_targets = self.test_labels

        nr_correct = 0
        for i in range(len(predicted_targets)):
            if predicted_targets[i] == true_targets[i]:
                nr_correct += 1
        return 1 - nr_correct / len(predicted_targets)
