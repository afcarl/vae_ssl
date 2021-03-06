from AbstractSingleStochasticLayerSemiVAE import * 
from theano.compile.ops import as_op
from special import Psi, Polygamma
from randomvariates import randomLogGamma
import random
        
@as_op(itypes=[T.fmatrix,T.fscalar],otypes=[T.fmatrix])
def rng_loggamma_(beta,seed):
    vfunc = np.vectorize(randomLogGamma)
    random.seed(float(seed))
    return vfunc(beta).astype(config.floatX)

class LogGammaSemiVAE(AbstractSingleStochasticLayerSemiVAE):

    def rng_loggamma(self, beta):
        seed=self.srng.uniform(size=(1,),low=-1.0e10,high=1.0e10)[0]
        return rng_loggamma_(beta,seed)

    def logpdf_loggamma(self, X, beta):
        """
                         log probability density function for loggamma
        """
        return (X*beta-T.exp(X)-T.gammaln(beta)).sum(axis=1,keepdims=True)
        

    def loggamma_kl(self, beta, betaprior):
        """
        KL Term for LogGamma Variates
        """
        KL = (T.gammaln(betaprior)-T.gammaln(beta)-(betaprior-beta)*Psi()(beta)).sum(1,keepdims=True)
        return KL

    def variational_loggamma(self, beta, betaprior):
        #generate loggamma variates, need to cut off gradient calcs through as_op
        #dim=[batchsize,nclasses]
        loggamma_variates = theano.gradient.disconnected_grad(self.rng_loggamma(beta))
        #calculate KL
        #dim=[batchsize,1]
        KL = self.loggamma_kl(beta, betaprior)
        return loggamma_variates, KL

    def variational_dirichlet(self,beta,betaprior):
        #U = loggamma variates
        U, KL_loggamma = self.variational_loggamma(beta,betaprior)
        #convert to Dirichlet (with sharpening)
        if self.tWeights['sharpening'] != 1:
            alpha = T.nnet.softmax(U*self.tWeights['sharpening'])
        else:
            alpha = T.nnet.softmax(U)
        return alpha, KL_loggamma

    def build_classifier(self, XL, Y):
        _, logbeta = self.build_inference_alpha(XL)
        probs = T.nnet.softmax(logbeta)
        #T.nnet.categorical_crossentropy returns a vector of length batch_size
        loss= T.nnet.categorical_crossentropy(probs,Y) 
        accuracy = T.eq(T.argmax(probs,axis=1),Y)
        return probs, loss, accuracy

    def build_inference_alpha(self, X): 
        """
        return h(x), logbeta(h(x))
        """
        if not self._evaluating:
            X = self.dropout(X,self.params['input_dropout'])
            self._p(('Inference with dropout :%.4f')%(self.params['input_dropout']))


        with self.namespaces('h(x)'):
            hx = self.build_hidden_layers(X,diminput=self.params['dim_observations']
                                          ,dimoutput=self.params['q_dim_hidden']
                                          ,nlayers=self.params['q_layers'])

        with self.namespaces('h_logbeta'):
            h_logbeta = self.build_hidden_layers(hx,diminput=self.params['q_dim_hidden']
                                                  ,dimoutput=self.params['q_dim_hidden']
                                                  ,nlayers=self.params['alpha_inference_layers'])

        if not self._evaluating:
            h_logbeta = self.dropout(h_logbeta,self.params['dropout_logbeta']) 

        with self.namespaces('logbeta'):
            logbeta = self.linear(h_logbeta,diminput=self.params['q_dim_hidden']
                                            ,dimoutput=self.params['nclasses'])

        #clip to avoid nans
        logbeta = T.clip(logbeta,-5,5)

        self.tOutputs['logbeta'] = logbeta
        return hx, logbeta

    def build_vae(self, X, eps, Y=None):
        """
        Build VAE subgraph to do inference and emissions 
        (if Y==None, build upper bound of -logp(x), else build upper bound of -logp(x,y)

        returns a bunch of VAE outputs
        """
        betaprior = self.tHyperparams['betaprior']
        if Y is None:
            self._p(('Building graph for lower bound of logp(x)'))
        else:
            self._p(('Building graph for lower bound of logp(x,y)'))

        # build h(x) and logbeta
        hx, logbeta = self.build_inference_alpha(X)

        beta = T.exp(logbeta)
        if Y is not None: 
            """
            -logp(x,y)
            """

            if self.params['logpxy_discrete']:
                # assume alpha = Y
                nllY = theano.shared(-np.log(0.1))
                KL_loggamma = theano.shared(0.)
                alpha = Y
            else:
                if self.params['learn_posterior']:
                    with self.namespaces('q(alpha|y)'):            
                        posterior = self.add_weights('posterior',np.asarray(1.))
                        beta += Y*T.nnet.softplus(posterior) 
                else:
                    beta += Y

                # select beta_y
                beta_y = (beta*Y).sum(axis=1)

                # calculate -logp(Y|alpha)
                nllY = Psi()(beta.sum(axis=1)) - Psi()(beta_y)

                # loggamma variates
                U, KL_loggamma = self.variational_loggamma(beta,betaprior)

                # convert to Dirichlet (with sharpening)
                sharpening = self.tHyperparams['sharpening']
                alpha = T.nnet.softmax(U*sharpening)
        else:
            """
            -logp(x)
            """

            # loggamma variates
            U, KL_loggamma = self.variational_loggamma(beta,betaprior)

            # convert to Dirichlet (with sharpening)
            alpha = T.nnet.softmax(U*self.tHyperparams['sharpening'])

        mu, logcov2 = self.build_inference_Z(alpha,hx)

        # gaussian variates
        Z, KL_Z = self.variational_gaussian(mu,logcov2,eps)

        if not self._evaluating:
            # adding noise during training usually helps performance
            Z = Z + self.srng.normal(Z.shape,0,0.05,dtype=config.floatX)

        # generative model
        paramsX = self.build_generative(alpha, Z)
        if self.params['data_type']=='real':
            nllX = self.nll_gaussian(X,**paramsX).sum(axis=1)
        else:
            nllX = self.nll_bernoulli(X,**paramsX).sum(axis=1)

        # negative of the lower bound
        KL = KL_loggamma.sum() + KL_Z.sum()
        NLL = nllX.sum()
        if Y is not None:
            NLL += nllY.sum()
        bound = KL + NLL 

        # objective function
        if self._evaluating:
            objfunc = bound 
        else: 
            # annealing (training only)
            anneal = self.tHyperparams['annealing']

            # annealed objective function
            objfunc = anneal['KL_alpha']*KL_loggamma.sum() + anneal['KL_Z']*KL_Z.sum() + NLL

            # gradient hack to do black box variational inference:
            if Y is None or self.params['logpxy_discrete']==False:
                # previous if statement checks to see if we need to do inference over alpha
                # when self.params['logpxy_discrete']=True, we assume p(alpha|Y)=Y

                # make sure sizes are correct to prevent unintentional broadcasting
                KL_Z = KL_Z.reshape([-1])
                nllX = nllX.reshape([-1])

                if self.params['negKL']:
                    # the negative KL trick is something we found by accident that
                    # works well for when alpha is assumed to be loggamma or dirichlet
                    #negative KL trick :(
                    f = theano.gradient.disconnected_grad(-2.*KL_Z+nllX)
                else:
                    f = theano.gradient.disconnected_grad(anneal['KL_Z']*KL_Z+nllX)

                # apply gradient hack to objective function
                BBVIgradientHack = f*self.logpdf_loggamma(U,beta).reshape([-1])
                objfunc += BBVIgradientHack.sum()

        self.tOutputs.update({
                                'alpha':alpha,
                                'U':U,
                                'Z':Z,
                                'mu':mu,
                                'logcov2':logcov2,
                                #'paramsX':paramsX[0],
                                'logbeta':logbeta,
                                'bound':bound,
                                'objfunc':objfunc,
                                'nllX':nllX,
                                'KL_loggamma':KL_loggamma,
                                'KL_Z':KL_Z,
                                'KL':KL,
                                'NLL':NLL,
                                'eps':eps,
                             })
        if Y is not None:
            self.tOutputs.update({
                                'nllY':nllY
                                })

        return self.tOutputs


    def build_hyperparameters(self):
        super(LogGammaSemiVAE,self).build_hyperparameters()

        t = self.tWeights['update_ctr']
        with self.namespaces('annealing'):
            # annealing parameters
            aBP = self.add_weights('betaprior',np.asarray(0.))
            aBP_div = float(self.params['annealBP']) #50000.

            # updates
            self.add_update(aBP,T.switch(t/aBP_div>1,1.,0.01+t/aBP_div))

        # betaprior is annealed from self.params['betaprior'] to self.params['finalbeta']
        finalbeta  = float(self.params['finalbeta'])
        betaprior = self.params['betaprior']*(1-aBP)+self.params['finalbeta']*aBP

        # save all hyperparameters to tOutputs for access later
        self.tOutputs.update(self.tWeights)
        self.tOutputs['betaprior'] = betaprior

    def progress_bar_report_map(self):
        # see self.progress_bar_update for use
        # use list to preserve order
        report_map = super(LogGammaSemiVAE,self).progress_bar_report_map()
        return report_map +[
            ('hyperparameters/betaprior',lambda x:np.mean(x[-1]),'%0.5f (last)'),
        ]
    
