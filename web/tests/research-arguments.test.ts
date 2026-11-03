import {expect,test} from 'vitest';
import {parseArguments,formatArguments} from '../src/research/arguments';
test('saved argv preserves spaces, empty strings, quotes and Windows paths',()=>{
  const original=['--path','C:\\My Lab\\a.csv','','a"b\'c'];
  expect(parseArguments(formatArguments(original))).toEqual(original);
  expect(parseArguments('["a b", "", "C:\\\\Lab\\\\data.csv"]')).toEqual(['a b','','C:\\Lab\\data.csv']);
});
