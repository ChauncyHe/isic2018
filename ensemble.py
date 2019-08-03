import numpy as np
import pickle #将数据序列化以保存
import re #正则化
import os
import sys
import itertools #迭代工具
from glob import glob #文件路径查找
from sklearn.metrics import confusion_matrix, f1_score, auc, roc_curve #混淆矩阵，F1-Score,AUC，ROC曲线
from sklearn.ensemble import RandomForestClassifier #随机森林分类器
from sklearn.svm import SVC 
from joblib import Parallel, delayed # job.Parallel用于平行计算, joblib.delayed用于查询函数的全部参数
import multiprocessing #多进程处理库
import copy #复制模块


# Just assume fixed CV size for ensemble with evaluation
# 为了评估集成，而假设固定的交叉验证尺寸
cvSize = 5 #交叉验证折数
numClasses = 7 #分类类别数

# First argument is folder, filled with CV results files
# 第一个参数是包含交叉验证结果文件的文件夹
all_preds_path = sys.argv[1]

# Second argument indicates, whether we are only generating predictions or actually evaluating performance on something
# 第二个参数表明，是否只产生预测或者评估效果
if 'eval' in sys.argv[2]:
    evaluate = True
    # Determin if vote or average is used
    if 'vote' in sys.argv[2]:
        evaluate_method = 'vote' #评估方式为投票
    else:
        evaluate_method = 'average' #评估方式为平均
    # Determine if exhaustive combination search or ordered search is used
    if 'exhaust' in sys.argv[2]:
        exhaustive_search = True #详尽搜索模式
        num_top_models = [int(s) for s in re.findall(r'\d+',sys.argv[2])][-1]
    else:
        exhaustive_search = False
    # Third argument indicates where subset should be saved
    if 'subSet' in sys.argv[3]:
        subSetPath = sys.argv[3] #第三个参数，子集保存路径
    else:
        subSetPath = None
else:
    evaluate = False
    acceptedList = []
    if 'last' in sys.argv[2]:
        acceptedList.append('last')
    if 'best' in sys.argv[2]:
        acceptedList.append('best')
    if 'meta' in sys.argv[2]:
        acceptedList.append('meta')                
    # Third argument indicates whether some subset should be used
    if 'subSet' in sys.argv[3]: 
        # Load subset file
        with open(sys.argv[3],'rb') as f:
            subSetDict = pickle.load(f) #加载子集文件字典   
        subSet = subSetDict['subSet']
    else:
        subSet = None    

# Fourth argument indicates csv path to save final results into
if len(sys.argv) > 4 and 'csvFile' in sys.argv[4]:
    csvPath = sys.argv[4] #CSV文件保存路径
    origFilePath = sys.argv[5] #原始文件路径
else:
    csvPath = None


def get_metrics(predictions,targets):
    """
     返回一些需要用到的度量
     Args:
        predictions: 预测值
        targets: 目标值
     Return:
        ACC:精确度
        F1: F1-Score
        WACC:
        ROC_AUC:
    """
    
    # Calculate metrics
    # Accuarcy
    acc = np.mean(np.equal(np.argmax(predictions,1),np.argmax(targets,1)))
    # Confusion matrix
    conf = confusion_matrix(np.argmax(targets,1),np.argmax(predictions,1))     
    # Class weighted accuracy
    wacc = conf.diagonal()/conf.sum(axis=1)  
    # Auc
    fpr = {}
    tpr = {}
    roc_auc = np.zeros([numClasses])
    for i in range(numClasses):
        fpr[i], tpr[i], _ = roc_curve(targets[:, i], predictions[:, i])
        roc_auc[i] = auc(fpr[i], tpr[i])       
    # F1 Score
    f1 = f1_score(np.argmax(predictions,1),np.argmax(targets,1),average='weighted')        
    # Print
    print("Accuracy:",acc)
    print("F1-Score:",f1)
    print("WACC:",wacc)
    print("Mean WACC:",np.mean(wacc))
    print("AUC:",roc_auc)
    print("Mean Auc:",np.mean(roc_auc))        
    return acc, f1, wacc, roc_auc

# If its actual evaluation, evaluate each CV indipendently, show results both for each CV set and all of them together
# 独立评估每一次交叉验证
if evaluate:
    # Go through all files
    files = sorted(glob(all_preds_path+'/*')) #查找路径下所有文件，返回文件绝对路径的列表(os.listdir()只返回文件名列表)
    # Because of unkown prediction size, dont use matrix
    final_preds = {}
    final_targets = {}
    all_waccs = []
    accum_preds = {}
    # Define each pred size in loop
    firstLoaded = False
    for j in range(len(files)):
        # Skip if it is a directory
        if os.path.isdir(files[j]): #如果是文件夹
            continue
        # Skip if not a pkl file
        if '.pkl' not in files[j]: #预测文件夹中没有pickle的文件.pkl
            print("Remove non-pkl files")
            break
        # Load file
        with open(files[j],'rb') as f: #加载.pkl文件
            allDataCurr = pickle.load(f)    
        # Get predictions
        if not firstLoaded:
            # Define accumulated prediction size
            for i in range(cvSize):
                accum_preds[i] = np.zeros([len(files),len(allDataCurr['bestPred'][i]),numClasses])
            firstLoaded = True
        # Write preds into array
        #print(files[j],allDataCurr['bestPred'][0].shape)
        wacc_avg = 0
        for i in range(cvSize):
            accum_preds[i][j,:,:] = allDataCurr['bestPred'][i]
            final_targets[i] = allDataCurr['targets'][i]
            # Confusion matrix
            conf = confusion_matrix(np.argmax(allDataCurr['targets'][i],1),np.argmax(allDataCurr['bestPred'][i],1))     
            # Class weighted accuracy
            wacc_avg += np.mean(conf.diagonal()/conf.sum(axis=1))  
        wacc_avg = wacc_avg/cvSize    
        all_waccs.append(wacc_avg)         
        # Print performance of model + name
        print("Model:",files[j],"WACC:",wacc_avg)
    # Print results per cv
    # Averaging predictions
    f1_avg = 0
    acc_avg = 0
    auc_avg = np.zeros([numClasses])
    wacc_avg = np.zeros([numClasses])
    # Voting with predictions
    f1_vote = 0
    acc_vote = 0
    auc_vote = np.zeros([numClasses])
    wacc_vote = np.zeros([numClasses])
    # Linear SVM on predictions
    f1_linsvm = 0
    acc_linsvm = 0
    auc_linsvm = np.zeros([numClasses])
    wacc_linsvm = np.zeros([numClasses])
    # RF on predictions
    f1_rf = 0
    acc_rf = 0
    auf_rf = np.zeros([numClasses])
    wacc_rf = np.zeros([numClasses])
    # Helper function to determine top combination
    def evalEnsemble(currComb):
        currWacc = 0
        for i in range(cvSize):
            if evaluate_method == 'vote':
                pred_argmax = np.argmax(accum_preds[i][currComb,:,:],2)   
                pred_eval = np.zeros([pred_argmax.shape[1],numClasses]) 
                for j in range(pred_eval.shape[0]):
                    pred_eval[j,:] = np.bincount(pred_argmax[:,j],minlength=numClasses)  
            else:
                pred_eval = np.mean(accum_preds[i][currComb,:,:],0)
            # Confusion matrix
            conf = confusion_matrix(np.argmax(final_targets[i],1),np.argmax(pred_eval,1))     
            # Class weighted accuracy
            currWacc += np.mean(conf.diagonal()/conf.sum(axis=1))       
        currWacc = currWacc/cvSize
        return currWacc       
    if exhaustive_search:
        # First: determine best subset based on average CV wacc
        # Select best subset based on wacc metric
        # Only take top N models
        top_inds = np.argsort(-np.array(all_waccs))
        elements = top_inds[:num_top_models]
        allCombs = []
        for L in range(0, len(elements)+1):
            for subset in itertools.combinations(elements, L):
                allCombs.append(subset)
                #print(subset)
        print("Number of combinations",len(allCombs))
        print("Models considered")
        for i in range(len(elements)):
            print("ID",elements[i],files[elements[i]]) 
        #allWaccs = np.zeros([len(allCombs)])
        num_cores = multiprocessing.cpu_count()
        print("Cores available",num_cores)
        allWaccs = Parallel(n_jobs=num_cores)(delayed(evalEnsemble)(comb) for comb in allCombs)
        # Sort by highest value
        allWaccsSrt = -np.sort(-np.array(allWaccs))
        srtInds = np.argsort(-np.array(allWaccs))
        allCombsSrt = np.array(allCombs)[srtInds]
        for i in range(5):
            print("Top",i+1)
            print("Best WACC",allWaccsSrt[i])            
            print("Best Combination:",allCombsSrt[i])
            print("Corresponding File Names")
            subSetDict = {}
            subSetDict['subSet'] = []
            for j in allCombsSrt[i]:
                print("ID",j,files[j])  
                # Add filename without last part, indicating the type "best/last/meta/full"
                if i == 0:                
                    subSetDict['subSet'].append(files[j])                     
        bestComb = allCombsSrt[0]     
    else:
        # Only take top N models
        top_inds = np.argsort(-np.array(all_waccs))
        # Go through all top N combs
        allWaccs = np.zeros([len(top_inds)])
        allCombs = []
        for i in range(len(top_inds)):
            allCombs.append([])
            if i==0:
                allCombs[i].append(top_inds[0])
            else:
                allCombs[i] = copy.deepcopy(allCombs[i-1])
                allCombs[i].append(top_inds[i])
            # Test comb
            allWaccs[i] = evalEnsemble(allCombs[i])
        # Sort by highest value
        allWaccsSrt = -np.sort(-np.array(allWaccs))
        srtInds = np.argsort(-np.array(allWaccs))
        allCombsSrt = np.array(allCombs)[srtInds]
        for i in range(len(top_inds)):
            print("Top",i+1)
            print("WACC",allWaccsSrt[i])            
            print("Combination:",allCombsSrt[i])
            if i == 0:
                subSetDict = {}
                subSetDict['subSet'] = []
                for j in allCombsSrt[i]:
                    print("ID",j,files[j])  
                    # Add filename without last part, indicating the type "best/last/meta/full"
                    subSetDict['subSet'].append(files[j])
        print("Corresponding File Names")  
        for j in allCombs[-1]:
            print("ID",j,files[j])                          
        bestComb = allCombsSrt[0]    
    # Save subset for later
    if subSetPath is not None:
        with open(subSetPath, 'wb') as f:
            pickle.dump(subSetDict, f, pickle.HIGHEST_PROTOCOL)              
    #for i in range(cvSize):
    #    print("CV Set",i+1)
    #    print("----------------------------------")                
    #    # Averaging
    #    pred_avg = np.mean(accum_preds[i,bestComb,:,:],0)
    #    # Get metrics and print
    #    print("Averaging")
    #    print("-----------------")
    #   acc, f1, wacc, roc_auc = get_metrics(pred_avg,final_targets[i,:,:])
    #    # Save for total eval
    #    f1_avg += f1; acc_avg += acc; auc_avg += roc_auc; wacc_avg += wacc
    #    # Voting
    #    pred_argmax = np.argmax(accum_preds[i,bestComb,:,:],2)   
    #    pred_vote = np.zeros([pred_argmax.shape[1],numClasses]) 
    #    #print(pred_argmax.shape,pred_vote.shape)
    #    for j in range(pred_vote.shape[0]):
    #        pred_vote[j,:] = np.bincount(pred_argmax[:,j],minlength=numClasses)      
    #    # Get metrics and print
    #    print("Voting")
    #    print("-----------------")
    #    acc, f1, wacc, roc_auc = get_metrics(pred_vote,final_targets[i,:,:])
    #    # Save for total eval
    #    f1_vote += f1; acc_vote += acc; auc_vote += roc_auc; wacc_vote += wacc    
    #    # Linear SVM + RF does not make sense here
    # Total evaluation
    #print("All Sets")
    #print("Averaging")
    #print("-----------------")   
    #print("Accuracy:",acc_avg/cvSize)
    #print("F1-Score:",f1_avg/cvSize)
    #print("WACC:",wacc_avg/cvSize)
    #print("Mean WACC:",np.mean(wacc_avg/cvSize))
    #print("AUC:",auc_avg/cvSize)
    #print("Mean Auc:",np.mean(auc_avg/cvSize))   
    #print("Voting")
    #print("-----------------")   
    #print("Accuracy:",acc_vote/cvSize)
    #print("F1-Score:",f1_vote/cvSize)
    #print("WACC:",wacc_vote/cvSize)
    #print("Mean WACC:",np.mean(wacc_vote/cvSize))
    #print("AUC:",auc_vote/cvSize)
    #print("Mean Auc:",np.mean(auc_vote/cvSize))      

else:
    # Only generate predictions. All models predict on the same set -> cv models are equal to full models here    
    # Go through all files
    files = sorted(glob(all_preds_path+'/*'))
    # Because of unkown prediction size, only determin it in the loop
    firstLoaded = False
    ind = 0
    for j in range(len(files)):
        # Skip if not a pkl file
        if '.pkl' not in files[j]:
            continue
        # Potentially check, if this file is among the selected subset
        if subSet is not None:
            # Search
            found = False
            for name in subSet:
                _, name_only = name.split('ISIC')
                if name_only in files[j]:
                    found = True
                    break
            if not found:
                # Check extra for acceptedList inclusion
                for name in subSet:
                    _, name_only = name.split('ISIC')
                    if name_only[:-13] in files[j]:
                        found = True
                        break
                if not found:
                    continue
                # Then check, whether this type of "best,last,meta,full" is desired
                found = False
                for name in acceptedList:
                    if name in files[j]:
                        found = True
                        break
                if not found:
                    continue            
        # Load file
        with open(files[j],'rb') as f:
            allDataCurr = pickle.load(f)    
        # Get predictions
        if not firstLoaded:
            # Define final prediction/targets size, assume fixed CV size
            final_preds = np.zeros([len(allDataCurr['extPred'][0]),numClasses])
            # Define accumulated prediction size
            accum_preds = np.expand_dims(allDataCurr['extPred'][0],0)
            ind += 1
            if len(allDataCurr['extPred']) > 1:
                for i in range(1,len(allDataCurr['extPred'])):
                    accum_preds = np.concatenate((accum_preds,np.expand_dims(allDataCurr['extPred'][i],0)),0)
                    ind += 1
            else:
                # Just repeat the first model X times
                for i in range(1,5):
                    accum_preds = np.concatenate((accum_preds,np.expand_dims(allDataCurr['extPred'][0],0)),0)
                    ind += 1                
            firstLoaded = True
        else:
            # Write preds into array
            if len(allDataCurr['extPred']) > 1:
                for i in range(len(allDataCurr['extPred'])):
                    accum_preds = np.concatenate((accum_preds,np.expand_dims(allDataCurr['extPred'][i],0)),0)
                    ind += 1
            else:
                # Just repeat the first model X times
                for i in range(0,5):
                    accum_preds = np.concatenate((accum_preds,np.expand_dims(allDataCurr['extPred'][0],0)),0)
                    ind += 1                       
        print(files[j])
    # Resize array to actually used size
    print(accum_preds.shape)
    final_preds = accum_preds[:ind,:,:]
    print(final_preds.shape)
    # Average for final predictions
    final_preds = np.mean(final_preds,0)
    class_pred = np.argmax(final_preds,1)
    print(np.mean(final_preds,0))
    # Write into csv file, according to ordered list
    if csvPath is not None:
        # Get order file names from original folder
        files = sorted(glob(origFilePath+'/*'))
        # save into formatted csv file
        with open(csvPath, 'w') as csv_file:
            # First line
            csv_file.write("image,MEL,NV,BCC,AKIEC,BKL,DF,VASC\n")
            ind = 0
            for file_name in files:
                if 'ISIC_' not in file_name:
                    continue
                splits = file_name.split('\\')
                name = splits[-1]
                name, _ = name.split('.')
                csv_file.write(name + "," + str(final_preds[ind,0]) + "," +  str(final_preds[ind,1]) + "," + str(final_preds[ind,2]) + "," + str(final_preds[ind,3]) + "," + str(final_preds[ind,4]) + "," + str(final_preds[ind,5]) + "," + str(final_preds[ind,6]) + "\n")
                ind += 1


