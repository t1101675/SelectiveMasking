# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Create masked LM/next sentence masked_lm TF examples for BERT."""
from __future__ import absolute_import, division, print_function, unicode_literals

import torch
import argparse
import logging
import os
import random
from io import open
import h5py
import numpy as np
from tqdm import tqdm, trange
import json
import pickle

from tokenization import BertTokenizer
import tokenization as tokenization

import random
import collections
import mask_utils.mask_generators as mask_generators
from run_classifier_dataset_utils import processors
from sc_mask_gen import SC, ModelGen
from rand_mask_gen import RandMask



class TrainingInstance(object):
    """A single training instance (sentence pair)."""
    def __init__(self, tokens, segment_ids, masked_lm_positions, masked_lm_labels, is_random_next):
        self.tokens = tokens
        self.segment_ids = segment_ids
        self.is_random_next = is_random_next
        self.masked_lm_positions = masked_lm_positions
        self.masked_lm_labels = masked_lm_labels

    def __str__(self):
        s = ""
        s += "tokens: %s\n" % (" ".join(
            [tokenization.printable_text(x) for x in self.tokens]))
        s += "segment_ids: %s\n" % (" ".join([str(x) for x in self.segment_ids]))
        s += "is_random_next: %s\n" % self.is_random_next
        s += "masked_lm_positions: %s\n" % (" ".join(
            [str(x) for x in self.masked_lm_positions]))
        s += "masked_lm_labels: %s\n" % (" ".join(
            [tokenization.printable_text(x) for x in self.masked_lm_labels]))
        s += "\n"
        return s

    def __repr__(self):
        return self.__str__()


def write_instance_to_example_file(instances, tokenizer, max_seq_length,
                                    max_predictions_per_seq, output_file):
    """Create TF example files from `TrainingInstance`s."""
    
    total_written = 0
    features = collections.OrderedDict()
    
    num_instances = len(instances)
    features["input_ids"] = np.zeros([num_instances, max_seq_length], dtype="int32")
    features["input_mask"] = np.zeros([num_instances, max_seq_length], dtype="int32")
    features["segment_ids"] = np.zeros([num_instances, max_seq_length], dtype="int32")
    features["masked_lm_positions"] = np.zeros([num_instances, max_predictions_per_seq], dtype="int32")
    features["masked_lm_ids"] = np.zeros([num_instances, max_predictions_per_seq], dtype="int32")
    features["next_sentence_labels"] = np.zeros(num_instances, dtype="int32")


    for inst_index, instance in enumerate(tqdm(instances, desc="Writing Instances")):
        input_ids = tokenizer.convert_tokens_to_ids(instance.tokens)
        input_mask = [1] * len(input_ids)
        segment_ids = list(instance.segment_ids)
        assert len(input_ids) <= max_seq_length

        while len(input_ids) < max_seq_length:
            input_ids.append(0)
            input_mask.append(0)
            segment_ids.append(0)

        assert len(input_ids) == max_seq_length
        assert len(input_mask) == max_seq_length
        assert len(segment_ids) == max_seq_length

        masked_lm_positions = list(instance.masked_lm_positions)
        masked_lm_ids = tokenizer.convert_tokens_to_ids(instance.masked_lm_labels)
        masked_lm_weights = [1.0] * len(masked_lm_ids)

        while len(masked_lm_positions) < max_predictions_per_seq:
            masked_lm_positions.append(0)
            masked_lm_ids.append(0)
            masked_lm_weights.append(0.0)

        next_sentence_label = 1 if instance.is_random_next else 0



        features["input_ids"][inst_index] = input_ids
        features["input_mask"][inst_index] = input_mask
        features["segment_ids"][inst_index] = segment_ids
        features["masked_lm_positions"][inst_index] = masked_lm_positions
        features["masked_lm_ids"][inst_index] = masked_lm_ids
        features["next_sentence_labels"][inst_index] = next_sentence_label

        total_written += 1

        # if inst_index < 20:
        #   tf.logging.info("*** Example ***")
        #   tf.logging.info("tokens: %s" % " ".join(
        #       [tokenization.printable_text(x) for x in instance.tokens])      
        #   for feature_name in features.keys():
        #     feature = features[feature_name]
        #     values = []
        #     if feature.int64_list.value:
        #       values = feature.int64_list.value
        #     elif feature.float_list.value:
        #       values = feature.float_list.value
        #     tf.logging.info(
        #         "%s: %s" % (feature_name, " ".join([str(x) for x in values])))


    print("saving data")
    f= h5py.File(output_file, 'w')
    f.create_dataset("input_ids", data=features["input_ids"], dtype='i4', compression='gzip')
    f.create_dataset("input_mask", data=features["input_mask"], dtype='i1', compression='gzip')
    f.create_dataset("segment_ids", data=features["segment_ids"], dtype='i1', compression='gzip')
    f.create_dataset("masked_lm_positions", data=features["masked_lm_positions"], dtype='i4', compression='gzip')
    f.create_dataset("masked_lm_ids", data=features["masked_lm_ids"], dtype='i4', compression='gzip')
    f.create_dataset("next_sentence_labels", data=features["next_sentence_labels"], dtype='i1', compression='gzip')
    f.flush()
    f.close()

def write_labeled_data(labeled_data, output_file):
    with open(output_file, "wb") as f:
        pickle.dump(labeled_data, f)

def split_mask(all_documents, num_parts, rng):
    pass        


def create_training_instances(data, all_labels, task_name, generator, max_seq_length, dupe_factor, short_seq_prob, masked_lm_prob, max_predictions_per_seq, rng, with_rand=False):
    """Create `TrainingInstance`s from raw text."""

    # Remove empty documents
    if with_rand:
        all_documents, rand_all_documents = generator(data, all_labels, dupe_factor, rng)
        print(len(all_documents), len(rand_all_documents))
    else:
        all_documents = generator(data, all_labels, dupe_factor, rng)        
        print(len(all_documents))

    instances = []
    all_documents = [x for x in all_documents if x]
    rng.shuffle(all_documents)
    for document_index in range(len(all_documents)):
        instances.extend(create_instances_from_document(all_documents, document_index, max_seq_length, short_seq_prob,
            masked_lm_prob, max_predictions_per_seq, rng))

    rng.shuffle(instances)

    labeled_data = []
    for document in all_documents:
        for sentence in document:
            labeled_data.append((sentence.tokens, [1 if x else 0 for x in sentence.info]))

    if with_rand:
        rand_instances = []
        rand_all_documents = [x for x in rand_all_documents if x]
        rng.shuffle(rand_all_documents)
        for document_index in range(len(rand_all_documents)):
            rand_instances.extend(create_instances_from_document(rand_all_documents, document_index, max_seq_length, short_seq_prob,
                masked_lm_prob, max_predictions_per_seq, rng))
    
        rng.shuffle(rand_instances)
    
        return instances, rand_instances, labeled_data
    else:
        return instances, labeled_data        


def create_instances_from_document(
    all_documents, document_index, max_seq_length, short_seq_prob,
    masked_lm_prob, max_predictions_per_seq, rng):
    """Creates `TrainingInstance`s for a single document."""

    # document: MaskedTokenInstance: (tokens, info)
    document = all_documents[document_index]

    # Account for [CLS], [SEP]
    max_num_tokens = max_seq_length - 2

    # We *usually* want to fill up the entire sequence since we are padding
    # to `max_seq_length` anyways, so short sequences are generally wasted
    # computation. However, we *sometimes*
    # (i.e., short_seq_prob == 0.1 == 10% of the time) want to use shorter
    # sequences to minimize the mismatch between pre-training and fine-tuning.
    # The `target_seq_length` is just a rough target however, whereas
    # `max_seq_length` is a hard limit.
    target_seq_length = max_num_tokens
    if rng.random() < short_seq_prob:
        target_seq_length = rng.randint(2, max_num_tokens)

    # We DON'T just concatenate all of the tokens from a document into a long
    # sequence and choose an arbitrary split point because this would make the
    # next sentence prediction task too easy. Instead, we split the input into
    # segments "A" and "B" based on the actual "sentences" provided by the user
    # input.
    instances = []
    current_chunk = []
    current_length = 0
    i = 0
    while i < len(document):
        segment = document[i] # segment: MaskedTokenInstance (tokens, info)
        current_chunk.append(segment)
        current_length += len(segment.tokens)
        if i == len(document) - 1 or current_length >= target_seq_length:
            if current_chunk:
                # `a_end` is how many segments from `current_chunk` go into the `A`
                # (first) sentence.
                # a_end = 1
                # if len(current_chunk) >= 2:
                #   a_end = rng.randint(1, len(current_chunk) - 1)

                tokens_a = []
                m_info_a = []
                # for j in range(a_end):
                for j in range(len(current_chunk)):
                    tokens_a.extend(current_chunk[j].tokens)
                    m_info_a.extend(current_chunk[j].info)
                truncate_seq_pair(tokens_a, m_info_a, [], [], max_num_tokens, rng)

                assert len(tokens_a) >= 1
                # assert len(tokens_b) >= 1

                tokens = []
                m_info = []
                segment_ids = []
                tokens.append("[CLS]")
                m_info.append({})
                segment_ids.append(0)
                for token, info in zip(tokens_a, m_info_a):
                    tokens.append(token)
                    m_info.append(info)
                    segment_ids.append(0)

                tokens.append("[SEP]")
                m_info.append({})
                segment_ids.append(0)

                masked_lm_positions = [index for index in range(len(m_info)) if m_info[index]]
                if len(masked_lm_positions) > max_predictions_per_seq:
                    rng.shuffle(masked_lm_positions)
                    masked_lm_positions = masked_lm_positions[0:max_predictions_per_seq]
                    masked_lm_positions.sort()
                # masks = [m_info[pos]["mask"] for pos in masked_lm_positions]
                masked_lm_labels = [m_info[pos]["label"] for pos in masked_lm_positions]
                
                for pos in masked_lm_positions:
                    tokens[pos] = m_info[pos]["mask"]

                is_random_next = False
                instance = TrainingInstance(
                    tokens=tokens,
                    segment_ids=segment_ids,
                    is_random_next=is_random_next,
                    masked_lm_positions=masked_lm_positions,
                    masked_lm_labels=masked_lm_labels)
                instances.append(instance)
                # print(tokens, masked_lm_positions, masked_lm_labels)
            current_chunk = []
            current_length = 0  
        i += 1
    return instances

MaskedLmInstance = collections.namedtuple("MaskedLmInstance", ["index", "label"])
MaskedTokenInstance = collections.namedtuple("MaskedTokenInstance", ["tokens", "info"])

def truncate_seq_pair(tokens_a, m_info_a, tokens_b, m_info_b, max_num_tokens, rng):
    """Truncates a pair of sequences to a maximum sequence length."""
    while True:
        total_length = len(tokens_a) + len(tokens_b)
        if total_length <= max_num_tokens:
            break

        (trunc_tokens, trunc_info) = (tokens_a, m_info_a) if len(tokens_a) > len(tokens_b) else (tokens_b, m_info_b)
        assert len(trunc_tokens) >= 1

        # We want to sometimes truncate from the front and sometimes from the
        # back to add more randomness and avoid biases.
        if rng.random() < 0.5:
            del trunc_tokens[0]
            del trunc_info[0]
        else:
            trunc_tokens.pop()
            trunc_info.pop()


def main():
    print(torch.cuda.is_available())
    parser = argparse.ArgumentParser()
    ## Required parameters
    parser.add_argument("--input_dir",
                        default=None,
                        type=str,
                        required=True,
                        help="The input train corpus. can be directory with .txt files or a path to a single file")
    parser.add_argument("--output_dir",
                        default=None,
                        type=str,
                        required=True,
                        help="The output file where the model checkpoints will be written.")

    ## Other parameters

    # bool
    parser.add_argument("--mode", 
                        type=str,
                        )

    # str
    parser.add_argument("--bert_model", 
                        default="bert-large-uncased", 
                        type=str, 
                        required=False,
                        help="Bert pre-trained model selected in the list: bert-base-uncased, "
                              "bert-large-uncased, bert-base-cased, bert-base-multilingual, bert-base-chinese.")
    parser.add_argument("--task_name", 
                        default="", 
                        type=str,
                        required=False)
    parser.add_argument("--gpus", 
                        default=0,
                        type=int)
    parser.add_argument("--local_rank",
                        default=0,
                        type=int)

    # int 
    parser.add_argument("--max_seq_length",
                        default=128,
                        type=int,
                        help="The maximum total input sequence length after WordPiece tokenization. \n"
                             "Sequences longer than this will be truncated, and sequences shorter \n"
                             "than this will be padded.")
    parser.add_argument("--dupe_factor",
                        default=1,
                        type=int,
                        help="Number of times to duplicate the input data (with different masks).")
    parser.add_argument("--max_predictions_per_seq",
                        default=20,
                        type=int,
                        help="Maximum sequence length.")
    parser.add_argument("--sentence_batch_size",
                        default=256, 
                        type=int)
    parser.add_argument("--top_sen_rate",
                        default=0.8,
                        type=float)
    parser.add_argument("--threshold",
                        default=0.2,
                        type=float)
                             

    # floats

    parser.add_argument("--masked_lm_prob",
                        default=0.15,
                        type=float,
                        help="Masked LM probability.")

    parser.add_argument("--short_seq_prob",
                        default=0.1,
                        type=float,
                        help="Probability to create a sequence shorter than maximum sequence length")

    parser.add_argument("--do_lower_case",
                        action='store_true',
                        help="Whether to lower case the input text. True for uncased models, False for cased models.")
    parser.add_argument('--random_seed',
                        type=int,
                        default=12345,
                        help="random seed for initialization")
    parser.add_argument('--part',
                        type=int,
                        default=0)
    parser.add_argument('--max_proc',
                        type=int, 
                        default=1)
    parser.add_argument('--with_rand',
                        action='store_true'
                        )
    parser.add_argument('--split_part',
                        type=int
                        )

    args = parser.parse_args()
    print(args)
    tokenizer = BertTokenizer.from_pretrained(args.bert_model, do_lower_case=args.do_lower_case)
    logger = logging.getLogger(__name__)
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s -   %(message)s',
                        datefmt='%m/%d/%Y %H:%M:%S',
                        level=logging.INFO if args.local_rank in [-1, 0] else logging.WARN)
    rng = random.Random(args.random_seed)
    np.random.seed(args.random_seed)
    torch.manual_seed(args.random_seed)

    print("creating instance from {}".format(args.input_dir))
    processor = processors[args.task_name]()
    eval_examples = processor.get_pretrain_examples(args.input_dir, args.part, args.max_proc)
    # print(len(eval_examples))
    data = [example.text_a for example in eval_examples]
    # print(data)
    all_labels = [example.label for example in eval_examples]
    del eval_examples
    
    label_list = processor.get_labels()
    logger.info("Bert Model: " + args.bert_model)
    print(torch.cuda.is_available())
    if args.mode == "rand":
        print("Mode: rand")
        generator = RandMask(args.masked_lm_prob, args.bert_model, args.do_lower_case, args.max_seq_length)
    elif args.mode == "rule":
        print("Mode: rule", )    
        generator = SC(args.masked_lm_prob, args.top_sen_rate, args.threshold, args.bert_model, args.do_lower_case, args.max_seq_length, label_list, args.sentence_batch_size)
    else:
        print("Mode: model")
        generator = ModelGen(args.masked_lm_prob, args.bert_model, args.do_lower_case, args.max_seq_length, args.sentence_batch_size, with_rand=args.with_rand)
    # input_files = []
    # print(args.part)
    if args.with_rand:
        instances, rand_instances, labeled_data = create_training_instances(
            data, all_labels, args.task_name, generator, args.max_seq_length, args.dupe_factor,
            args.short_seq_prob, args.masked_lm_prob, args.max_predictions_per_seq,
            rng, with_rand=args.with_rand)
    else:
        instances, labeled_data = create_training_instances(
            data, all_labels, args.task_name, generator, args.max_seq_length, args.dupe_factor,
            args.short_seq_prob, args.masked_lm_prob, args.max_predictions_per_seq,
            rng, with_rand=args.with_rand)

    if args.part >= 0:
        output_file = os.path.join(args.output_dir, "{}.hdf5".format(args.part))        
        if args.with_rand:
            rand_output_file = os.path.join(args.output_dir, "rand_{}.hdf5".format(args.part))
        labeled_output_file = os.path.join(args.output_dir, "{}.pkl".format(args.part))     
    else:
        output_file = os.path.join(args.output_dir, "0.hdf5") 
        if args.with_rand:
            rand_output_file = os.path.join(args.output_dir, "rand_0.hdf5")
        labeled_output_file = os.path.join(args.output_dir, "0.pkl")
    
    print(len(instances))
    if args.with_rand:
        print(len(rand_instances))
    write_instance_to_example_file(instances, tokenizer, args.max_seq_length, args.max_predictions_per_seq, output_file)
    if args.with_rand:
        write_instance_to_example_file(rand_instances, tokenizer, args.max_seq_length, args.max_predictions_per_seq, rand_output_file)

    if args.mode == "rule":
        print("write labeled data for rule mode")
        write_labeled_data(labeled_data, labeled_output_file)

if __name__ == "__main__":
    main()
