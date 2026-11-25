import { ActionButton, Button, Content, Dialog, DialogTrigger, Divider, Flex, Heading, Item, Link, Picker, Switch, Text } from '@adobe/react-spectrum';
import Settings from '@spectrum-icons/workflow/Settings';
import { useIntake } from './store';

/** Knobs for playing with the mock: none of this exists in the real app. */
export function MockControls() {
  const { s, setMock, reset, loadSample, view } = useIntake();
  return (
    <div className="mockfab">
      <DialogTrigger type="popover" placement="bottom start">
        <ActionButton isQuiet aria-label="Mock controls"><Settings /><Text>Mock controls</Text></ActionButton>
        <Dialog width="size-4600">
          <Heading>Mock controls</Heading>
          <Divider />
          <Content>
            <Flex direction="column" gap="size-200">
              <Text>Nothing in this mock calls a server or a model. These switches change what the fake one does.</Text>
              <Picker label="Speed" selectedKey={String(s.mock.speed)} onSelectionChange={(k) => setMock({ speed: Number(k) })} width="100%">
                <Item key="1">Realistic</Item>
                <Item key="2">Fast</Item>
                <Item key="6">Very fast</Item>
                <Item key="30">Instant</Item>
              </Picker>
              <Switch isSelected={s.mock.modelOn} onChange={(on) => setMock({ modelOn: on })}>Model available (API key set)</Switch>
              <Switch isSelected={s.mock.failNext} onChange={(on) => setMock({ failNext: on })}>Next upload cannot be read</Switch>
              <Text>
                Sample files to drop in (PDF, Word, Excel, text; two calls):{' '}
                <Link><a href="/samples/albany-cctv-sample-bid.zip" download>download the zip</a></Link>, or find them in web/mock/public/samples.
              </Text>
              <Flex gap="size-100" wrap>
                <Button variant="secondary" onPress={() => { loadSample(); }}>Load sample bid</Button>
                <Button variant="negative" style="outline" onPress={() => { reset(); view('bids'); }}>Start over</Button>
              </Flex>
            </Flex>
          </Content>
        </Dialog>
      </DialogTrigger>
    </div>
  );
}
