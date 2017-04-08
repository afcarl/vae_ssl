class Namespace(dict):

    def __init__(self, data={}, convert_children=True, **kwargs):
		"""
		Wrapper for dict with methods adapted for the hierarchical nature of dictionaries.
		data: {dict,list,iterator,Namespace} if iterable and not of type dict, each element of iterable must have length 2
		convert_children: recursively convert all children in data to Namespace types
		e.g.
		>> x = Namespace({(1,1):{2:{3:4,5:6},'a':9}},convert_children=False)
		>> print x
		{
		 (1, 1): {
		   a: 9
		   2: {
			 3: 4
			 5: 6
			}
		  }
		}
		>> type(x[(1,1)])
		dict	
		>> y = Namespace(x,convert_children=True)
		>> type(y[(1,1)])
		__main__.Namespace
		"""
        super(Namespace,self).__init__(data,**kwargs)
        if convert_children:
            def _apply_func(d):
                if isinstance(d,dict):
                    return Namespace(d,convert_children=True)
                else:
                    return d
            temp = self.apply(_apply_func)
            for k in temp.keys():
                self[k] = temp[k]
    
    def __setitem__(self, key, item):
        super(Namespace,self).__setitem__(key,item)
        if isinstance(item, Namespace):
            item._set_parent(self,key)

    def _set_parent(self,parent_obj,parent_key):
        self._parent_obj = parent_obj
        self._parent_key = parent_key
        
    def path(self):
		"""
		if current namespace is the child of a parent namespace, return
		the keypath from the root namespace to the current namespace.
		e.g.
		>> x = Namespace({1:{2:{3:4}}},convert_children=True)
		>> x[1][2].path()
		[1,2]
		"""
        if hasattr(self,'_parent_key'):
            return self._parent_obj.path()+[self._parent_key]
        else:
            return []
    
    def __repr__(self):
        def _repr_func(d,level=0):
            indent='  '*level
            r = {}
            for k,v in d.iteritems():
                if isinstance(v,dict):
                    r[k] = _repr_func(v,level+1)
                else:
                    r[k] = v
            return '{\n'+('\n'.join('%s%s: %s' % (indent+' ',k,v) for k,v in r.iteritems()))+'\n%s}'%indent
        return _repr_func(self)
        
    def walk(self):
		"""
		returns an iterator that walks depth-first through namespace
		e.g.
		>> a = Namespace({'(1,1)':{2:{3:4,5:'6'},'a':9}})
		>> print a
		{
		 (1, 1): {
		   a: 9
		   2: {
			 3: 4
			 5: 6
			}
		  }
		}	
		>> for k,v in a.walk(): print k,v
		((1, 1), 'a') 9
		((1, 1), 2, 3) 4
		((1, 1), 2, 5) 6
		"""
        def _walk(d,path=[]):
            for k in d.keys():
                path=path+[k]
                if isinstance(d[k],dict):
                    for sub in _walk(d[k],path):
                        yield sub
                else:
                    yield tuple(path),d[k]
        for sub in _walk(self):
            yield sub

    def flatten(self,join=None):
		"""
		 converts hierarchical Namespace to Namespace of depth 1
		 join: {str,None}, when join is not None, keypath elements are converted to string and joined by '/'
		 e.g. Namespace({'a':{'b':1}}) becomes Namespace({'a/b':1})
		"""
        if join:
            assert isinstance(join,str),'join must be a type of string'
            return Namespace({join.join(k):v for k,v in self.apply(str,nodes=True).walk()})
        else:
            return Namespace(self.walk())
        
    def leaves(self):
		"""
		returns all leaves in Namespace flattened into a list
		"""
        return zip(*self.walk())[1]

    def updatepath(self,keypath,value):
		"""
		e.g.
		>> a = Namespace()
		>> a.updatepath([1,2,3],4)
		>> print a
		{
		 1: {
		   2: {
			 3: 4
			}
		  }
		}
		"""
        k = keypath[0]
        if len(keypath) > 1:
            if k not in self.keys():
                self[k] = Namespace()
            self[k].updatepath(keypath[1:],value)
        else:
            self[k] = value	
            
    def apply(self,func,nodes=False,*args,**kwargs):
		"""
		recursively apply func to Namespace
		nodes: {True,False} defaults to False, if True, apply func to nodes, else apply func to leaves
		*args, **kwargs: args and kwargs of func
		e.g.
		>> Namespace({(1,1):{2:{3:4,5:6},'a':9}}).apply(lambda x: 2*x)
		{
		 (1, 1): {
		   a: 18
		   2: {
			 3: 8
			 5: 12
			}
		  }
		}
		>> Namespace({(1,1):{2:{3:4,5:6},'a':9}}).apply(lambda x: str(x)+'!',nodes=True)
		{
		 (1, 1)!: {
		   a!: 9
		   2!: {
			 3!: 4
			 5!: 6
			}
		  }
		}
		"""
        def _apply(d1,func,*args,**kwargs):
            d2 = Namespace(convert_children=False)
            for k1 in d1.keys():
                if nodes:
                    k2 = func(k1)
                else:
                    k2 = k1
                if isinstance(d1[k1],Namespace):
                    d2[k2] = _apply(d1[k1],func,*args,**kwargs)
                else:
                    if nodes:
                        d2[k2] = d1[k1]
                    else:
                        d2[k2] = func(d1[k1],*args,**kwargs)
            return d2
        return _apply(self,func,*args,**kwargs)

        
